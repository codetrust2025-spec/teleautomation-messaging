"""Telegram membership (On Telegram) refresh — staleness, scan, WebSocket push."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING, Callable, Awaitable

from core.account_info_store import load_account_info, save_account_info
from core.config import (
    ACCOUNTS,
    MEMBERSHIP_MIN_RETRY_SECONDS,
    MEMBERSHIP_STALE_SECONDS,
)
from features.telegram_joined_stats import fetch_joined_counts

if TYPE_CHECKING:
    from workers.account_worker import AccountWorker

logger = logging.getLogger(__name__)

_last_refresh_attempt: dict[str, float] = {}
_refresh_locks: dict[str, asyncio.Lock] = {}


def _slot_lock(slot: str) -> asyncio.Lock:
    if slot not in _refresh_locks:
        _refresh_locks[slot] = asyncio.Lock()
    return _refresh_locks[slot]


def parse_joined_updated_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    try:
        if text.endswith(" IST"):
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M IST")
            return dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        if text.endswith(" UTC"):
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M UTC")
            return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        s = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def membership_age_seconds(info: dict | None) -> float | None:
    if not info:
        return None
    updated = parse_joined_updated_at(info.get("joined_updated_at"))
    if not updated:
        return None
    return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())


def is_membership_stale(
    info: dict | None,
    *,
    threshold_seconds: int = MEMBERSHIP_STALE_SECONDS,
) -> bool:
    if not info or not info.get("phone"):
        return False
    if info.get("joined_total") is None:
        return True
    age = membership_age_seconds(info)
    if age is None:
        return True
    return age > threshold_seconds


def membership_meta(info: dict | None) -> dict:
    age = membership_age_seconds(info)
    stale = is_membership_stale(info)
    return {
        "membership_stale": stale,
        "membership_age_seconds": int(age) if age is not None else None,
    }


def membership_payload(slot: str, info: dict) -> dict:
    meta = membership_meta(info)
    return {
        "type": "membership",
        "slot": slot,
        "joined_groups": info.get("joined_groups", 0),
        "joined_channels": info.get("joined_channels", 0),
        "joined_total": info.get("joined_total", 0),
        "joined_updated_at": info.get("joined_updated_at", ""),
        "membership_stale": meta["membership_stale"],
        "membership_age_seconds": meta["membership_age_seconds"],
    }


async def push_membership_update(slot: str, info: dict) -> None:
    from core import broadcast

    await broadcast.broadcast(membership_payload(slot, info))


async def _scan_via_string_session(slot: str) -> dict:
    from core.dm_string_session import run_with_string_session

    return await run_with_string_session(slot, fetch_joined_counts, attempts=2)


async def _scan_via_worker(slot: str, worker: AccountWorker) -> dict:
    from core.telegram_client import release_session, run_group_operation

    await release_session(slot, wait=1.5)

    async def _op(client):
        return await fetch_joined_counts(client)

    try:
        return await run_group_operation(slot, _op, attempts=3)
    finally:
        await release_session(slot, wait=0.5)


def _apply_stats(slot: str, base: dict, stats: dict, worker: AccountWorker) -> dict:
    from core.subscription_accounts import enrich_account_info

    scan_debug = stats.pop("_scan_debug", None)
    if scan_debug and scan_debug.get("partial"):
        stats["joined_scan_partial"] = True
        stats["joined_scan_partial_reason"] = str(scan_debug.get("partial_reason") or "")
    prev_total = int(base.get("joined_total") or 0)
    if (
        int(stats.get("joined_total") or 0) == 0
        and prev_total > 0
        and scan_debug
        and int(scan_debug.get("total_dialogs") or 0) == 0
    ):
        raise RuntimeError("scan returned 0 dialogs — session may be locked")

    info = enrich_account_info(slot, {**base, **stats})
    worker.state.account_info = info
    save_account_info(slot, info)
    try:
        from core.posting_mode import clear_joined_targets_cache

        clear_joined_targets_cache(slot)
    except Exception:
        pass
    if scan_debug:
        logger.info(
            "membership_scan %s: total=%s groups=%s channels=%s dialogs=%s elapsed=%ss",
            slot,
            stats.get("joined_total"),
            stats.get("joined_groups"),
            stats.get("joined_channels"),
            scan_debug.get("total_dialogs"),
            scan_debug.get("elapsed_seconds"),
        )
    return info


async def refresh_membership(
    slot: str,
    worker: AccountWorker,
    *,
    reason: str = "",
    notify: bool = True,
    push_state: Callable[[], Awaitable[None]] | None = None,
) -> dict | None:
    """
    Refresh On Telegram counts without blocking the worker when possible.
    Uses string session first; falls back to worker session when idle.
    """
    if slot not in ACCOUNTS:
        return None

    async with _slot_lock(slot):
        now = time.monotonic()
        last = _last_refresh_attempt.get(slot, 0.0)
        if now - last < MEMBERSHIP_MIN_RETRY_SECONDS and reason not in (
            "join_success",
            "manual",
            "dashboard_open",
            "worker_cycle",
        ):
            return worker.state.account_info or load_account_info(slot)
        _last_refresh_attempt[slot] = now

        base = worker.state.account_info or load_account_info(slot)
        if not base or not base.get("phone"):
            return None

        stats: dict | None = None
        errors: list[str] = []

        try:
            stats = await _scan_via_string_session(slot)
            logger.info("membership_scan %s via string session (%s)", slot, reason or "auto")
        except Exception as e:
            errors.append(f"string:{type(e).__name__}")

        if stats is None and not worker.state.running:
            try:
                stats = await _scan_via_worker(slot, worker)
                logger.info("membership_scan %s via worker session (%s)", slot, reason or "auto")
            except Exception as e:
                errors.append(f"worker:{type(e).__name__}:{e}")

        if stats is None:
            if worker.state.running:
                worker.request_joined_scan()
                logger.info(
                    "membership_scan %s queued on worker (%s) — %s",
                    slot,
                    reason or "auto",
                    "; ".join(errors[:2]),
                )
            else:
                logger.warning(
                    "membership_scan %s failed (%s): %s",
                    slot,
                    reason or "auto",
                    "; ".join(errors[:3]),
                )
            return base

        try:
            info = _apply_stats(slot, base, stats, worker)
        except RuntimeError as e:
            logger.warning("membership_scan %s rejected: %s", slot, e)
            if worker.state.running:
                worker.request_joined_scan()
            return base

        if notify:
            await push_membership_update(slot, info)
            if push_state:
                await push_state()
            else:
                await worker._notify()
        return info


async def refresh_membership_after_join(
    slot: str,
    worker: AccountWorker,
    *,
    push_state: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Non-blocking post-join refresh (optimistic bump already applied)."""
    await asyncio.sleep(2.0)
    try:
        await refresh_membership(
            slot,
            worker,
            reason="join_success",
            notify=True,
            push_state=push_state,
        )
    except Exception as e:
        logger.warning("post-join membership refresh %s: %s", slot, e)
        worker.request_joined_scan()
