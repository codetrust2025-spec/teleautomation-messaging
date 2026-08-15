"""
Interval forwarding — random batch per tick, then rest until next tick.

Each tick picks a random count between 60 and 100 (capped by remaining pool) from
joined groups not yet used this round. When every joined group has been used once,
the pool resets and a new round begins. Short pauses apply between sub-batches.
A random 10–30 minute rest is between tick starts.

Forwarding-only: every 2 completed forward ticks the worker joins one group from this
account's master slice (respects daily join limits). Campaign mode never uses this path;
campaign joins only via the unified scheduler during posting cycles.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass, field

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from core.telegram_forward import native_forward_message
from core.forward_message_batch import load_forward_batch_settings, split_into_batches
from core.posting_mode import (
    SOURCE_TELEGRAM,
    ForwardingSettings,
    load_joined_targets_cache,
    save_joined_targets_cache,
)
from core.structured_logging import LogEvent
from features.check_last_message import check_last_message
from features.group_operation import _wrap_error, process_group
from features.logging_feature import AccountLogger

FORWARD_TICK_COUNT_MIN = int(os.environ.get("FORWARD_TICK_MIN", "60"))
FORWARD_TICK_COUNT_MAX = int(os.environ.get("FORWARD_TICK_MAX", "100"))


@dataclass
class ForwardTickResult:
    forwarded: int = 0
    skipped: int = 0
    failed: int = 0
    failure_counts: dict[str, int] = field(default_factory=dict)
    total_targets: int = 0  # groups in this tick slice (≤ batch_size)
    joined_total: int = 0  # all joined groups on Telegram
    batch_size: int = 0
    total_batches: int = 0
    flood_seconds: int = 0
    hard_flood: bool = False
    end_reason: str = "complete"
    tick_group_offset: int = 0  # legacy UI; len(remaining pending) when saved
    next_tick_group_offset: int = 0
    next_tick_pending_keys: list[str] | None = None
    tick_round_reset: bool = False


@dataclass
class ForwardJoinResult:
    attempted: bool = False
    group: str = ""
    outcome: str = ""
    message: str = ""


def pick_forward_join_candidate(
    slot: str,
    groups: list[str],
    intel,
    *,
    start_index: int = 0,
) -> tuple[str | None, str]:
    """Next group from this account's master slice that may be joined."""
    from core.join_cycle import evaluate_join

    if not groups:
        return None, "no_groups_assigned"

    n = len(groups)
    for offset in range(n):
        group = groups[(start_index + offset) % n]
        if intel.get_membership_hint(group) == "member":
            continue
        decision = evaluate_join(slot, group)
        if decision.allowed:
            return group, "ok"
    return None, "no_eligible_group"


async def try_forward_periodic_join(
    slot: str,
    client: TelegramClient,
    logger: AccountLogger,
    intel,
    assigned_groups: list[str],
    *,
    cycle: int,
) -> ForwardJoinResult:
    """
    Forwarding-only periodic join: one group from the master slice.
    Called only from the forwarding loop (never from campaign).
    Respects evaluate_join limits; does not send a message after join.
    """
    from core.posting_mode import load_posting_mode

    if not load_posting_mode(slot).forwarding_enabled:
        result = ForwardJoinResult()
        result.outcome = "forwarding_disabled"
        result.message = "Forwarding disabled — no periodic join"
        return result

    from core.join_cycle import (
        evaluate_join,
        post_join_delay_seconds,
        record_join_attempt,
        record_join_failure,
        record_join_success,
    )
    from core.posting_mode import clear_joined_targets_cache
    from core.structured_logging import LogEvent
    from features.delay_handler import wait_seconds
    from features.group_operation import _join

    result = ForwardJoinResult()
    if not assigned_groups:
        result.outcome = "no_groups_assigned"
        result.message = "No groups in master list for this account"
        await logger.log_event(
            LogEvent.JOIN_SKIP,
            "info",
            reason=result.outcome,
            context="forwarding",
        )
        return result

    start_index = (max(1, cycle) // 2) % len(assigned_groups)
    group, pick_reason = pick_forward_join_candidate(
        slot, assigned_groups, intel, start_index=start_index
    )
    if not group:
        result.outcome = "skipped_no_candidate"
        result.message = pick_reason
        await logger.log_event(
            LogEvent.JOIN_SKIP,
            "info",
            reason=pick_reason,
            context="forwarding",
            cycle=cycle,
        )
        return result

    decision = evaluate_join(slot, group)
    if not decision.allowed:
        result.group = group
        result.outcome = "join_limited"
        result.message = decision.message
        await logger.log_event(
            LogEvent.JOIN_SKIP,
            "info",
            group=group,
            reason=decision.message,
            wait_sec=decision.wait_seconds,
            context="forwarding",
        )
        return result

    result.attempted = True
    result.group = group
    record_join_attempt(slot)
    await logger.log_event(
        LogEvent.JOIN_ATTEMPT, "info", group=group, context="forwarding", cycle=cycle
    )

    join_result = await _join(client, group)
    code = join_result if isinstance(join_result, str) else str(join_result)
    intel.record_join_outcome(group, code)

    if join_result == "joined_new":
        record_join_success(slot)
        intel.set_membership_hint(group, "member")
        clear_joined_targets_cache(slot)
        result.outcome = "joined_new"
        result.message = f"Joined {group}"
        await logger.log_event(
            LogEvent.JOIN_SUCCESS,
            "info",
            group=group,
            new_join=True,
            context="forwarding",
            cycle=cycle,
        )
        await wait_seconds(post_join_delay_seconds())
        return result

    if join_result == "already_in":
        intel.set_membership_hint(group, "member")
        result.outcome = "already_in"
        result.message = f"Already in {group}"
        await logger.log_event(
            LogEvent.JOIN_SUCCESS,
            "info",
            group=group,
            new_join=False,
            context="forwarding",
            cycle=cycle,
        )
        return result

    if isinstance(join_result, tuple) and join_result[0] == "flood":
        secs = int((join_result[1] or {}).get("seconds", 60))
        result.outcome = "flood"
        result.message = f"Flood wait {secs}s joining {group}"
        await logger.log_event(
            LogEvent.JOIN_FAIL,
            "warning",
            group=group,
            result="flood",
            flood_sec=secs,
            context="forwarding",
        )
        return result

    backoff = record_join_failure(slot, group)
    result.outcome = code
    result.message = f"Join failed for {group}: {code}"
    await logger.log_event(
        LogEvent.JOIN_FAIL,
        "warning",
        group=group,
        result=code,
        backoff_sec=backoff,
        context="forwarding",
    )
    return result


def _dest_peer(record: dict) -> str | int:
    username = (record.get("username") or "").strip()
    if username:
        return username if username.startswith("@") else f"@{username}"
    ent_id = record.get("id")
    if isinstance(ent_id, int):
        return ent_id
    raise ValueError("no peer for target")


async def load_forward_targets(
    slot: str,
    client: TelegramClient,
    *,
    include_channels: bool,
    force_refresh: bool = False,
) -> list[dict]:
    if not force_refresh:
        cached = load_joined_targets_cache(slot)
        if cached is not None:
            return cached

    from features.telegram_joined_stats import fetch_joined_dialog_details

    scan = await fetch_joined_dialog_details(client)
    rows = list(scan.get("targets") or [])
    if not include_channels:
        rows = [r for r in rows if r.get("type") == "group"]
    save_joined_targets_cache(slot, rows)
    return rows


async def _send_template_one(
    client: TelegramClient,
    dest: str | int,
    text: str,
    my_id: int,
    logger: AccountLogger,
) -> str:
    """Returns sent | skipped | failed | flood."""
    outcome = await process_group(
        client,
        dest,
        text,
        my_id,
        logger,
        planned_action="send",
    )
    if outcome == "sent":
        return "sent"
    if outcome == "skipped":
        return "skipped"
    if isinstance(outcome, tuple) and outcome[0] == "flood":
        return outcome
    if outcome in ("joined_sent",):
        return "sent"
    return "failed"


def _forward_failure_code(exc: Exception) -> str:
    code = _wrap_error(exc)
    if isinstance(code, tuple):
        if code[0] == "flood":
            return "flood"
        if code[0] == "error":
            detail = code[1] if len(code) > 1 and isinstance(code[1], dict) else {}
            return "session_error" if detail.get("session") else "error"
        return str(code[0])
    return str(code)


def _forward_failure_transient(exc: Exception) -> bool:
    code = _wrap_error(exc)
    if isinstance(code, tuple) and code[0] == "error":
        detail = code[1] if len(code) > 1 and isinstance(code[1], dict) else {}
        return bool(detail.get("session"))
    return False


def _record_forward_failure(result: ForwardTickResult, reason: str) -> None:
    key = (reason or "unknown")[:64]
    result.failure_counts[key] = result.failure_counts.get(key, 0) + 1


def _target_is_dead(record: dict, dead_peers: set[str] | None) -> bool:
    if not dead_peers:
        return False
    user = (record.get("username") or "").strip().lstrip("@").lower()
    name = (record.get("name") or "").strip().lower()
    if user and user in dead_peers:
        return True
    if name and name in dead_peers:
        return True
    rid = record.get("id")
    if rid is not None and str(rid) in dead_peers:
        return True
    return False


async def _forward_one(
    client: TelegramClient,
    dest: str | int,
    settings: ForwardingSettings,
    my_id: int,
    logger: AccountLogger,
) -> str | tuple:
    """Returns sent | skipped | ('failed', code) | flood tuple."""
    need = await check_last_message(client, dest, my_id, logger)
    if not need:
        return "skipped"

    async def _attempt() -> None:
        await native_forward_message(
            client,
            dest,
            settings.source_peer,
            settings.source_message_id,
            flood_retries=2,
        )

    try:
        await _attempt()
        return "sent"
    except FloodWaitError as e:
        return ("flood", {"seconds": int(e.seconds)})
    except Exception as exc:
        if _forward_failure_transient(exc):
            await asyncio.sleep(2)
            try:
                await _attempt()
                return "sent"
            except Exception as retry_exc:
                exc = retry_exc
        reason = _forward_failure_code(exc)
        await logger.log_event(
            LogEvent.SEND_FAIL,
            "warn",
            group=str(dest)[:120],
            error=reason,
            context="forwarding",
        )
        code = _wrap_error(exc)
        if code == "flood" or (isinstance(code, tuple) and code[0] == "flood"):
            return code
        return ("failed", reason)


def forward_target_key(record: dict) -> str:
    """Stable id for a joined group/channel row."""
    rid = record.get("id")
    if rid is not None:
        return f"id:{rid}"
    user = (record.get("username") or "").strip()
    if user:
        return f"@{user.lstrip('@')}"
    name = (record.get("name") or "").strip()
    if name:
        return f"name:{name}"
    return f"row:{id(record)}"


def targets_by_key(all_targets: list) -> dict[str, dict]:
    by_key: dict[str, dict] = {}
    for row in all_targets:
        if not isinstance(row, dict):
            continue
        by_key[forward_target_key(row)] = row
    return by_key


def normalize_forward_pending_keys(
    pending_keys: list[str] | None,
    by_key: dict[str, dict],
) -> list[str]:
    """Keep pending keys that still exist in the current joined scan."""
    if not pending_keys:
        return []
    return [k for k in pending_keys if k in by_key]


def pick_forward_tick_size(remaining: int) -> int:
    """Random 60–100 per tick; if fewer than 60 left, take all remaining."""
    remaining = max(0, int(remaining))
    if remaining <= 0:
        return 0
    if remaining < FORWARD_TICK_COUNT_MIN:
        return remaining
    hi = min(FORWARD_TICK_COUNT_MAX, remaining)
    return random.randint(FORWARD_TICK_COUNT_MIN, hi)


def pick_random_forward_tick_targets(
    all_targets: list,
    pending_keys: list[str] | None,
) -> tuple[list, int, list[str], bool]:
    """
    Return (targets_this_tick, joined_total, pending_pool_before_tick, round_reset).

    pending_pool_before_tick is the pool used for sampling; after the tick, remove
    only keys that were actually processed (sent/skip/fail).
    """
    by_key = targets_by_key(all_targets)
    joined_total = len(by_key)
    if joined_total <= 0:
        return [], 0, [], False

    pending = normalize_forward_pending_keys(pending_keys, by_key)
    round_reset = False
    if not pending:
        pending = list(by_key.keys())
        random.shuffle(pending)
        round_reset = True

    tick_size = pick_forward_tick_size(len(pending))
    if tick_size <= 0:
        return [], joined_total, [], round_reset

    picked_keys = random.sample(pending, tick_size)
    targets = [by_key[k] for k in picked_keys]
    return targets, joined_total, pending, round_reset


def slice_forward_tick_targets(
    all_targets: list,
    offset: int,
    per_tick_max: int,
) -> tuple[list, int, int]:
    """Legacy sequential slice — kept for tests; interval forward uses random pick."""
    joined_total = len(all_targets)
    if joined_total <= 0:
        return [], 0, 0
    per_tick = max(1, min(int(per_tick_max), joined_total))
    start = int(offset or 0) % joined_total
    end = start + per_tick
    if end <= joined_total:
        chunk = all_targets[start:end]
        next_offset = end % joined_total
    else:
        chunk = all_targets[start:]
        next_offset = 0
    return chunk, joined_total, next_offset


async def run_forward_tick(
    slot: str,
    client: TelegramClient,
    my_id: int,
    logger: AccountLogger,
    settings: ForwardingSettings,
    *,
    cycle: int = 1,
    should_continue,
    on_tick_begin=None,
    on_batch_begin=None,
    on_target_start=None,
    on_target_done=None,
    dead_peers: set[str] | None = None,
) -> ForwardTickResult:
    """
    Forward to a random 60–100 joined groups this tick (no reuse until round completes).
    Enhanced with adaptive intelligence for 10/10 performance.
    """
    from core.config import FLOOD_END_CYCLE_SECONDS, FLOOD_HARD_BAN_SECONDS
    from core.message_rewrite import prepare_cycle_message
    from core.forward_intelligence import (
        load_forward_intelligence,
        save_forward_intelligence,
        get_forward_dead_peers,
    )

    # Load intelligence system
    intel = load_forward_intelligence(slot)
    intel.record_tick_start()

    result = ForwardTickResult()
    if not settings.is_configured(slot):
        result.end_reason = "not_configured"
        save_forward_intelligence(intel)
        return result

    use_template = (settings.source_type or "").strip().lower() != SOURCE_TELEGRAM
    message_text = prepare_cycle_message(slot, cycle) if use_template else ""
    if use_template and not message_text.strip():
        result.end_reason = "not_configured"
        return result

    all_targets = await load_forward_targets(
        slot, client, include_channels=settings.include_channels
    )
    result.joined_total = len(all_targets)
    if not all_targets:
        result.end_reason = "no_targets"
        save_forward_intelligence(intel)
        return result

    batch_cfg = load_forward_batch_settings()
    targets, joined_total, pending_pool, round_reset = pick_random_forward_tick_targets(
        all_targets,
        getattr(settings, "tick_pending_keys", None),
    )
    result.joined_total = joined_total
    result.tick_round_reset = round_reset

    # Merge provided dead_peers with intelligence-tracked dead peers
    intel_dead = intel.get_dead_peer_set()
    all_dead_peers = (dead_peers or set()) | intel_dead

    if all_dead_peers:
        targets = [t for t in targets if not _target_is_dead(t, all_dead_peers)]
    result.total_targets = len(targets)
    if not targets:
        result.end_reason = "no_targets"
        result.next_tick_pending_keys = pending_pool
        result.next_tick_group_offset = len(pending_pool)
        save_forward_intelligence(intel)
        return result

    processed_keys: set[str] = set()
    batches = split_into_batches(targets, batch_cfg.batch_size)
    result.batch_size = batch_cfg.batch_size
    result.total_batches = len(batches)
    total = len(targets)
    dmin = batch_cfg.delay_min_seconds
    dmax = batch_cfg.delay_max_seconds
    batch_pause = batch_cfg.batch_pause_seconds

    if on_tick_begin:
        await on_tick_begin(
            total, result.total_batches, result.batch_size, result.joined_total
        )

    processed = 0

    for batch_idx, batch in enumerate(batches, start=1):
        if not should_continue():
            result.end_reason = "stopped"
            break

        if on_batch_begin:
            await on_batch_begin(batch_idx, result.total_batches, len(batch))

        for i, record in enumerate(batch):
            if not should_continue():
                result.end_reason = "stopped"
                break

            target_key = forward_target_key(record)
            try:
                dest = _dest_peer(record)
            except ValueError:
                _record_forward_failure(result, "no_peer")
                result.failed += 1
                processed += 1
                processed_keys.add(target_key)
                if on_target_done:
                    await on_target_done(
                        "failed", processed, total, batch_idx, fail_reason="no_peer"
                    )
                continue

            if _target_is_dead(record, dead_peers):
                continue

            label = (record.get("username") or record.get("name") or str(dest))[:80]
            if on_target_start:
                await on_target_start(label)

            if use_template:
                outcome = await _send_template_one(
                    client, dest, message_text, my_id, logger
                )
            else:
                outcome = await _forward_one(client, dest, settings, my_id, logger)

            tick_outcome = "failed"
            fail_reason = None
            if outcome == "sent":
                result.forwarded += 1
                tick_outcome = "sent"
                try:
                    from core.send_stats import record_send
                    from core.group_send_stats import record_group_send

                    record_send(slot, "forward")
                    record_group_send(slot, label)
                except Exception:
                    pass
            elif outcome == "skipped":
                result.skipped += 1
                tick_outcome = "skipped"
            elif isinstance(outcome, tuple) and outcome[0] == "failed":
                fail_reason = str(outcome[1] if len(outcome) > 1 else "unknown")
                _record_forward_failure(result, fail_reason)
                result.failed += 1
                tick_outcome = "failed"
                # Track persistent failures as dead peers
                if fail_reason in ("invalid", "blocked", "cant_write"):
                    intel.add_dead_peer(label, fail_reason)
            elif isinstance(outcome, tuple) and outcome[0] == "flood":
                secs = int((outcome[1] or {}).get("seconds", 60))
                result.flood_seconds = secs
                _record_forward_failure(result, "flood")
                result.failed += 1
                processed += 1

                # Record flood event in intelligence system
                intel.add_flood_event(secs, label)

                if on_target_done:
                    await on_target_done(
                        "failed", processed, total, batch_idx, fail_reason="flood"
                    )
                if secs >= FLOOD_HARD_BAN_SECONDS:
                    result.hard_flood = True
                    result.end_reason = "flood_break"
                    intel.record_tick_flooded()
                    save_forward_intelligence(intel)
                    break
                if secs >= FLOOD_END_CYCLE_SECONDS:
                    result.end_reason = "flood_break"
                    intel.record_tick_flooded()
                    save_forward_intelligence(intel)
                    break
                await asyncio.sleep(min(secs + random.randint(2, 8), 120))
                continue
            elif outcome == "failed":
                _record_forward_failure(result, "unknown")
                result.failed += 1
                tick_outcome = "failed"
            else:
                _record_forward_failure(result, "unknown")
                result.failed += 1
                tick_outcome = "failed"

            processed += 1
            processed_keys.add(target_key)
            if on_target_done:
                await on_target_done(
                    tick_outcome, processed, total, batch_idx, fail_reason=fail_reason
                )

            if not should_continue():
                result.end_reason = "stopped"
                break

            if i < len(batch) - 1 and dmax > 0:
                delay = random.uniform(dmin, dmax)
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline:
                    if not should_continue():
                        result.end_reason = "stopped"
                        return result
                    await asyncio.sleep(min(0.5, deadline - time.monotonic()))

        if result.end_reason in ("stopped", "flood_break"):
            break

        if batch_idx < result.total_batches and batch_pause > 0:
            pause_deadline = time.monotonic() + batch_pause
            while time.monotonic() < pause_deadline:
                if not should_continue():
                    result.end_reason = "stopped"
                    return result
                await asyncio.sleep(min(0.5, pause_deadline - time.monotonic()))

    pool = pending_pool or []
    remaining = [k for k in pool if k not in processed_keys]
    result.next_tick_pending_keys = remaining
    result.next_tick_group_offset = len(remaining)
    result.tick_group_offset = len(remaining)

    # Record successful tick completion if no flood break
    if result.end_reason not in ("flood_break", "stopped"):
        intel.record_tick_success()

    save_forward_intelligence(intel)
    return result
