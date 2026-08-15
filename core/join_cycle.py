"""
Join-group cycle — matches safe join flowchart.

Checks (in order):
  1. Account restricted (flood / cooldown)
  2. Already member (handled in group_operation after JoinChannelRequest)
  3. Daily new-join limit
  4. Too many new joins in last 2 hours (burst)
  5. Min interval since last successful new join
  6. Attempt join → success: record + post delay | failure: backoff + mark

State: data/accounts/{slot}/join_state.json
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from core.account_info_store import load_account_info, save_account_info
from core.config import (
    JOIN_COUNT_THRESHOLD,
    JOIN_COOLDOWN_SECONDS,
    JOIN_DAILY_LIMIT,
    JOIN_FAILURE_BACKOFF_MAX,
    JOIN_FAILURE_BACKOFF_MIN,
    JOIN_FAILURE_STREAK_CAP,
    JOIN_MIN_INTERVAL_SECONDS,
    JOIN_POST_JOIN_MAX_SECONDS,
    JOIN_POST_JOIN_MIN_SECONDS,
    JOIN_RECENT_MAX,
    JOIN_RECENT_WINDOW_SECONDS,
    STATE_DIR,
)
from core.ist_time import ist_date_str

_join_state_locks: dict[str, threading.Lock] = {}
_join_state_locks_guard = threading.Lock()


def _state_path(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, "join_state.json")


def _state_lock(slot: str) -> threading.Lock:
    with _join_state_locks_guard:
        lock = _join_state_locks.get(slot)
        if lock is None:
            lock = threading.Lock()
            _join_state_locks[slot] = lock
        return lock


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    d = dt or _utc_now()
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        s = str(raw).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _today_key() -> str:
    return ist_date_str()


def _default_state() -> dict:
    return {
        "daily_date": _today_key(),
        "daily_new_joins": 0,
        "recent_new_join_ts": [],
        "last_new_join_at": None,
        "last_attempt_at": None,
        "restriction_until": None,
        "group_failures": {},
    }


def load_join_state(slot: str) -> dict:
    path = _state_path(slot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        return _default_state()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            base = _default_state()
            base.update(raw)
            return base
    except Exception:
        pass
    return _default_state()


def save_join_state(slot: str, state: dict) -> None:
    path = _state_path(slot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _prune_recent(state: dict) -> list[float]:
    now = time.time()
    window = JOIN_RECENT_WINDOW_SECONDS
    raw = state.get("recent_new_join_ts") or []
    out: list[float] = []
    for item in raw:
        ts = item if isinstance(item, (int, float)) else _parse_iso(str(item))
        if ts and now - ts < window:
            out.append(float(ts))
    state["recent_new_join_ts"] = out
    return out


def _reset_daily_if_needed(state: dict) -> None:
    today = _today_key()
    if state.get("daily_date") != today:
        state["daily_date"] = today
        state["daily_new_joins"] = 0


def set_join_restriction(slot: str, until_ts: float) -> None:
    """Call when account hits heavy flood / ban — blocks new joins until time."""
    with _state_lock(slot):
        state = load_join_state(slot)
        state["restriction_until"] = _iso(datetime.fromtimestamp(until_ts, tz=timezone.utc))
        save_join_state(slot, state)
    save_account_info(slot, {"join_restricted_until": state["restriction_until"]})


def clear_join_restriction(slot: str) -> None:
    with _state_lock(slot):
        state = load_join_state(slot)
        state["restriction_until"] = None
        save_join_state(slot, state)


def restriction_remaining_seconds(slot: str) -> int:
    """Seconds until join/cycle restriction lifts (0 if none active)."""
    state = load_join_state(slot)
    restr = _parse_iso(state.get("restriction_until"))
    if restr and time.time() < restr:
        return max(1, int(restr - time.time()))
    return 0


def daily_join_count_for_reset(slot: str) -> int:
    """Raw automation join counter used as a display baseline during stats reset."""
    state = load_join_state(slot)
    if state.get("daily_date") != _today_key():
        return 0
    try:
        return max(0, int(state.get("daily_new_joins") or 0))
    except (TypeError, ValueError):
        return 0


def join_stats_for_ui(slot: str) -> dict:
    """Read-only automation join counters for the dashboard (/state)."""
    from core.account_profile import get_join_daily_limit

    state = load_join_state(slot)
    today = _today_key()
    daily = int(state.get("daily_new_joins") or 0)
    if state.get("daily_date") != today:
        daily = 0
    from core.stats_reset import get_join_reset_baseline

    display_daily = max(0, daily - get_join_reset_baseline(slot))
    until = _parse_iso(state.get("restriction_until"))
    now = time.time()
    return {
        "joins_today": display_daily,
        "joins_safety_count": daily,
        "joins_daily_limit": get_join_daily_limit(slot),
        "restriction_active": bool(until and now < until),
    }


def get_joined_total(slot: str) -> int:
    info = load_account_info(slot) or {}
    try:
        return max(0, int(info.get("joined_total") or 0))
    except (TypeError, ValueError):
        return 0


@dataclass
class JoinDecision:
    allowed: bool
    wait_seconds: int
    reason: str
    message: str


def evaluate_join(slot: str, group: str) -> JoinDecision:
    """Steps 1, 3, 4, 5 from join flowchart (step 2 = already_in at Telethon)."""
    with _state_lock(slot):
        state = load_join_state(slot)
        _reset_daily_if_needed(state)
        _prune_recent(state)
        save_join_state(slot, state)

    now = time.time()

    # 1 — account restricted
    restr = _parse_iso(state.get("restriction_until"))
    if restr and now < restr:
        left = int(restr - now)
        return JoinDecision(
            False,
            left,
            "account_restricted",
            f"Account restricted — skip join (retry in ~{left // 60}m)",
        )

    # Per-group failure streak → backoff skip
    fails = int((state.get("group_failures") or {}).get(group, 0))
    if fails >= JOIN_FAILURE_STREAK_CAP:
        return JoinDecision(
            False,
            JOIN_FAILURE_BACKOFF_MAX,
            "group_backoff",
            f"Group join failed {fails}x — skip until later cycles",
        )

    # 3 — daily limit (per-account profile may lower cap)
    from core.account_profile import get_join_daily_limit

    daily_limit = get_join_daily_limit(slot)
    daily = int(state.get("daily_new_joins") or 0)
    if daily >= daily_limit:
        return JoinDecision(
            False,
            3600,
            "daily_limit",
            f"Daily join limit reached ({daily}/{daily_limit}) — try tomorrow",
        )

    # 4 — burst in last 2h
    from core.account_profile import get_join_recent_max

    recent_max = get_join_recent_max(slot)
    recent = _prune_recent(state)
    if len(recent) >= recent_max:
        oldest = min(recent)
        left = int(JOIN_RECENT_WINDOW_SECONDS - (now - oldest)) + 1
        return JoinDecision(
            False,
            max(1, left),
            "recent_burst",
            f"Too many joins in last 2h ({len(recent)}/{recent_max}) — wait for next cycle",
        )

    # 5 — min interval since last new join (always; stricter when 100+ on Telegram)
    min_iv = JOIN_MIN_INTERVAL_SECONDS
    total = get_joined_total(slot)
    if total > JOIN_COUNT_THRESHOLD:
        min_iv = max(min_iv, JOIN_COOLDOWN_SECONDS)

    last_join = _parse_iso(state.get("last_new_join_at"))
    if last_join and now - last_join < min_iv:
        left = int(min_iv - (now - last_join)) + 1
        detail = f"last join {left // 60}m ago"
        if total > JOIN_COUNT_THRESHOLD:
            detail += f" ({total} groups on Telegram)"
        return JoinDecision(
            False,
            left,
            "min_interval",
            f"Too soon to join — {detail}",
        )

    return JoinDecision(True, 0, "ok", "")


def record_join_attempt(slot: str) -> None:
    with _state_lock(slot):
        state = load_join_state(slot)
        state["last_attempt_at"] = _iso()
        save_join_state(slot, state)


def record_join_success(slot: str) -> None:
    with _state_lock(slot):
        state = load_join_state(slot)
        _reset_daily_if_needed(state)
        now = time.time()
        state["last_new_join_at"] = _iso()
        state["last_attempt_at"] = state["last_new_join_at"]
        state["daily_new_joins"] = int(state.get("daily_new_joins") or 0) + 1
        recent = _prune_recent(state)
        recent.append(now)
        state["recent_new_join_ts"] = recent
        save_join_state(slot, state)
    save_account_info(slot, {"last_join_at": state["last_new_join_at"]})


def record_join_failure(slot: str, group: str) -> int:
    """Increment group failure count; return suggested backoff seconds."""
    with _state_lock(slot):
        state = load_join_state(slot)
        gf = dict(state.get("group_failures") or {})
        n = int(gf.get(group, 0)) + 1
        gf[group] = n
        state["group_failures"] = gf
        state["last_attempt_at"] = _iso()
        save_join_state(slot, state)
    # backoff tiers: 10-30m, 30m-2h, 2-12h, 12-24h
    tiers = [
        (600, 1800),
        (1800, 7200),
        (7200, 43200),
        (43200, 86400),
    ]
    idx = min(n - 1, len(tiers) - 1)
    lo, hi = tiers[idx]
    return random.randint(lo, hi)


def post_join_delay_seconds() -> float:
    return random.uniform(JOIN_POST_JOIN_MIN_SECONDS, JOIN_POST_JOIN_MAX_SECONDS)


# Backward-compatible API
def can_attempt_new_join(slot: str) -> tuple[bool, int, str]:
    d = evaluate_join(slot, "")
    if d.allowed:
        return True, 0, ""
    return False, d.wait_seconds, d.message


def record_new_join(slot: str) -> None:
    record_join_success(slot)
