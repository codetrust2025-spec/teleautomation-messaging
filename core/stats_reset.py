"""Global and per-account timestamps for resetting rolling daily / 24h stats (does not delete raw data)."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from core.config import DATA_DIR
from core.ist_time import ist_day_start_iso, ist_day_start_ts

ROLLING_WINDOW_SECONDS = 86400
MIN_RESET_INTERVAL_SECONDS = 2.0
AUTO_RESET_INTERVAL_SECONDS = ROLLING_WINDOW_SECONDS

_RESET_FILE = os.path.join(DATA_DIR, "stats_reset.json")
_lock = threading.Lock()
_last_reset_by_key: dict[str, float] = {}


class StatsResetDebounced(Exception):
    """Raised when reset requests arrive too quickly."""


@dataclass(frozen=True)
class AutoResetResult:
    """Returned when an automatic 24h stats period rollover runs."""

    scope: str  # "global" | "account"
    account_ids: tuple[str, ...]
    reset_timestamp: float


def _load() -> dict:
    if not os.path.exists(_RESET_FILE):
        return {}
    try:
        with open(_RESET_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = _RESET_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _RESET_FILE)


def _parse_ts(raw) -> float | None:
    if raw is None:
        return None
    try:
        ts = float(raw)
        return ts if ts > 0 else None
    except (TypeError, ValueError):
        return None


def get_reset_timestamp(account_id: str | None = None) -> float | None:
    """Unix time of last reset for account_id, or global reset if account_id is None."""
    with _lock:
        data = _load()
        if account_id:
            per = (data.get("per_account") or {}).get(account_id) or {}
            ts = _parse_ts(per.get("reset_timestamp"))
            if ts:
                return ts
        return _parse_ts(data.get("reset_timestamp"))


def get_reset_at_iso(account_id: str | None = None) -> str | None:
    ts = get_reset_timestamp(account_id)
    if not ts:
        return None
    from core.ist_time import format_ist_iso

    return format_ist_iso(ts)


def active_reset_timestamp(account_id: str | None = None, now: float | None = None) -> float | None:
    """Manual reset time if it happened today (IST); stale resets roll off at midnight IST."""
    now = now or time.time()
    day_start = ist_day_start_ts(now)
    if account_id:
        with _lock:
            per = (_load().get("per_account") or {}).get(account_id) or {}
        per_ts = _parse_ts(per.get("reset_timestamp"))
        if per_ts and per_ts >= day_start:
            return per_ts
    reset_ts = get_reset_timestamp()
    if reset_ts and reset_ts >= day_start:
        return reset_ts
    return None


def stats_window_kind(account_id: str | None = None, now: float | None = None) -> str:
    """since_reset = manual reset today; ist_day = midnight IST through now."""
    return "since_reset" if active_reset_timestamp(account_id, now) else "ist_day"


def get_effective_cutoff(account_id: str | None = None, now: float | None = None) -> float:
    """
    Count events with timestamp >= this value.
    Default window is the current IST calendar day (00:00 IST → now).
    A manual reset today moves the cutoff forward to that moment.
    """
    now = now or time.time()
    day_start = ist_day_start_ts(now)
    manual = active_reset_timestamp(account_id, now)
    if manual:
        return max(manual, day_start)
    return day_start


def get_join_reset_baseline(account_id: str) -> int:
    """Displayed joined count baseline captured at last stats reset (today IST only)."""
    if not active_reset_timestamp(account_id):
        return 0
    with _lock:
        data = _load()
        per = (data.get("per_account") or {}).get(account_id) or {}
        if "join_baseline" in per:
            try:
                return max(0, int(per.get("join_baseline") or 0))
            except (TypeError, ValueError):
                return 0
        baselines = data.get("join_baselines") or {}
        try:
            return max(0, int(baselines.get(account_id) or 0))
        except (AttributeError, TypeError, ValueError):
            return 0


def _is_reset_period_elapsed(reset_ts: float, now: float) -> bool:
    return reset_ts > 0 and (now - reset_ts) >= AUTO_RESET_INTERVAL_SECONDS


def _write_reset_timestamp(
    data: dict,
    *,
    ts: float,
    account_id: str | None,
    join_baselines: dict[str, int] | None,
) -> None:
    iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    baselines = {
        str(k): max(0, int(v or 0))
        for k, v in (join_baselines or {}).items()
    }
    if account_id:
        per = data.setdefault("per_account", {})
        if not isinstance(per, dict):
            per = {}
            data["per_account"] = per
        per[account_id] = {
            "reset_timestamp": ts,
            "reset_at": iso,
            "join_baseline": baselines.get(account_id, 0),
        }
    else:
        data["reset_timestamp"] = ts
        data["reset_at"] = iso
        data["per_account"] = {}
        data["join_baselines"] = baselines


def set_reset_timestamp(
    ts: float | None = None,
    account_id: str | None = None,
    *,
    join_baselines: dict[str, int] | None = None,
    skip_debounce: bool = False,
) -> float:
    """
    Set reset to now (or explicit ts) for one account or globally.
    Global reset clears per-account overrides so all accounts share the same window.
    """
    now = float(ts if ts is not None else time.time())
    debounce_key = account_id or "__global__"

    with _lock:
        if not skip_debounce:
            last = _last_reset_by_key.get(debounce_key, 0.0)
            if time.time() - last < MIN_RESET_INTERVAL_SECONDS:
                raise StatsResetDebounced("Please wait before resetting stats again.")
        data = _load()
        _write_reset_timestamp(
            data,
            ts=now,
            account_id=account_id,
            join_baselines=join_baselines,
        )
        _save(data)
        _last_reset_by_key[debounce_key] = time.time()
    return now


def maybe_auto_reset_24h(slots: list[str]) -> AutoResetResult | None:
    """
    Advance the stats window when 24h have elapsed since the last reset anchor.

    Only applies when a reset timestamp already exists (manual reset or prior auto reset).
    Rolling-only installs without stats_reset.json keep their sliding 24h window.
    """
    if not slots:
        return None

    now = time.time()
    with _lock:
        data = _load()
        global_ts = _parse_ts(data.get("reset_timestamp"))
        per = data.get("per_account") if isinstance(data.get("per_account"), dict) else {}

        if global_ts and _is_reset_period_elapsed(global_ts, now):
            from core.join_cycle import daily_join_count_for_reset

            baselines = {slot: daily_join_count_for_reset(slot) for slot in slots}
            ts = now
            _write_reset_timestamp(data, ts=ts, account_id=None, join_baselines=baselines)
            _save(data)
            _last_reset_by_key["__global__"] = now
            result = AutoResetResult("global", tuple(slots), ts)
        else:
            due_accounts: list[str] = []
            for slot in slots:
                row = per.get(slot) or {}
                per_ts = _parse_ts(row.get("reset_timestamp"))
                if per_ts and _is_reset_period_elapsed(per_ts, now):
                    due_accounts.append(slot)
            if not due_accounts:
                return None

            from core.join_cycle import daily_join_count_for_reset

            ts = now
            for slot in due_accounts:
                baselines = {slot: daily_join_count_for_reset(slot)}
                _write_reset_timestamp(
                    data,
                    ts=ts,
                    account_id=slot,
                    join_baselines=baselines,
                )
                _last_reset_by_key[slot] = now
            _save(data)
            result = AutoResetResult("account", tuple(due_accounts), ts)

    from core.send_stats import invalidate_cache

    if result.scope == "global":
        invalidate_cache()
    else:
        for slot in result.account_ids:
            invalidate_cache(slot)
    return result


def clear_reset_timestamp() -> None:
    """Dev/testing only — revert to rolling 24h window."""
    with _lock:
        if os.path.exists(_RESET_FILE):
            try:
                os.remove(_RESET_FILE)
            except OSError:
                pass
