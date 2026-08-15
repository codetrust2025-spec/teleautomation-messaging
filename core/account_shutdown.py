"""Auto-shutdown list — accounts with no successful posts for too long rest 1 week."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from core.config import DATA_DIR

NO_POST_THRESHOLD_SECONDS = int(
    os.environ.get("ACCOUNT_NO_POST_SHUTDOWN_SECONDS", str(6 * 3600))
)
SHUTDOWN_DURATION_SECONDS = int(
    os.environ.get("ACCOUNT_SHUTDOWN_DURATION_SECONDS", str(7 * 86400))
)

_SHUTDOWN_FILE = os.path.join(DATA_DIR, "account_shutdown.json")
_lock = threading.Lock()


def _load() -> dict:
    if not os.path.exists(_SHUTDOWN_FILE):
        return {}
    try:
        with open(_SHUTDOWN_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = _SHUTDOWN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _SHUTDOWN_FILE)


def _entry(slot: str, raw: dict) -> dict[str, Any]:
    shutdown_at = float(raw.get("shutdown_at") or 0)
    resume_at = float(raw.get("resume_at") or 0)
    if resume_at <= 0 and shutdown_at > 0:
        resume_at = shutdown_at + SHUTDOWN_DURATION_SECONDS
    return {
        "slot": slot,
        "shutdown_at": shutdown_at,
        "resume_at": resume_at,
        "reason": str(raw.get("reason") or "no_post_6h"),
        "was_running": bool(raw.get("was_running", True)),
        "last_send_at": raw.get("last_send_at"),
    }


def list_shutdowns(*, active_only: bool = True) -> dict[str, dict[str, Any]]:
    now = time.time()
    out: dict[str, dict[str, Any]] = {}
    with _lock:
        for slot, raw in (_load().get("accounts") or {}).items():
            if not isinstance(raw, dict):
                continue
            entry = _entry(str(slot), raw)
            if active_only and now >= float(entry.get("resume_at") or 0):
                continue
            out[str(slot)] = entry
    return out


def get_shutdown_info(slot: str) -> dict[str, Any] | None:
    if not slot:
        return None
    with _lock:
        raw = (_load().get("accounts") or {}).get(slot)
        if not isinstance(raw, dict):
            return None
        entry = _entry(slot, raw)
    if time.time() >= float(entry.get("resume_at") or 0):
        return None
    return entry


def is_shutdown_active(slot: str) -> bool:
    return get_shutdown_info(slot) is not None


def seconds_until_resume(slot: str) -> int:
    info = get_shutdown_info(slot)
    if not info:
        return 0
    return max(0, int(float(info.get("resume_at") or 0) - time.time()))


def shutdown_info_for_ui(slot: str) -> dict[str, Any] | None:
    info = get_shutdown_info(slot)
    if not info:
        return None
    resume_at = float(info.get("resume_at") or 0)
    from core.ist_time import format_ist_iso

    resume_iso = format_ist_iso(resume_at) if resume_at > 0 else None
    return {
        "active": True,
        "reason": info.get("reason"),
        "shutdown_at": info.get("shutdown_at"),
        "resume_at": resume_at,
        "resume_at_iso": resume_iso,
        "seconds_until_resume": seconds_until_resume(slot),
        "was_running": bool(info.get("was_running")),
        "last_send_at": info.get("last_send_at"),
    }


def put_on_shutdown_list(
    slot: str,
    *,
    reason: str = "no_post_6h",
    was_running: bool = True,
    last_send_at: float | None = None,
) -> dict[str, Any]:
    if not slot:
        raise ValueError("slot required")
    now = time.time()
    entry = {
        "shutdown_at": now,
        "resume_at": now + SHUTDOWN_DURATION_SECONDS,
        "reason": reason,
        "was_running": bool(was_running),
        "last_send_at": last_send_at,
    }
    with _lock:
        data = _load()
        accounts = data.setdefault("accounts", {})
        accounts[slot] = entry
        _save(data)
    return _entry(slot, entry)


def clear_shutdown(slot: str) -> bool:
    if not slot:
        return False
    with _lock:
        data = _load()
        accounts = data.get("accounts") or {}
        if slot not in accounts:
            return False
        del accounts[slot]
        data["accounts"] = accounts
        _save(data)
    return True


def clear_all_shutdowns() -> list[str]:
    """Remove every active shutdown entry; returns cleared slot ids."""
    with _lock:
        data = _load()
        accounts = data.get("accounts") or {}
        if not accounts:
            return []
        cleared = [str(slot) for slot in accounts.keys()]
        data["accounts"] = {}
        _save(data)
    return cleared


def purge_expired() -> list[str]:
    """Remove expired shutdown entries; returns slots cleared."""
    now = time.time()
    cleared: list[str] = []
    with _lock:
        data = _load()
        accounts = data.get("accounts") or {}
        keep = {}
        for slot, raw in accounts.items():
            if not isinstance(raw, dict):
                continue
            entry = _entry(str(slot), raw)
            if now >= float(entry.get("resume_at") or 0):
                cleared.append(str(slot))
            else:
                keep[str(slot)] = raw
        if cleared:
            data["accounts"] = keep
            _save(data)
    return cleared


def account_expected_to_post(slot: str, worker_state) -> bool:
    """True when campaign or forwarding is enabled and worker is (or should be) active."""
    from core.posting_mode import load_posting_mode
    from core.worker_persistence import load_running_slots

    cfg = load_posting_mode(slot)
    if not cfg.campaign_enabled and not cfg.forwarding_enabled:
        return False
    if getattr(worker_state, "campaign_running", False) or getattr(
        worker_state, "forwarding_running", False
    ):
        return True
    if getattr(worker_state, "running", False):
        return True
    return slot in load_running_slots()


def evaluate_posting_idle(
    slot: str,
    worker_state,
    *,
    now: float | None = None,
) -> tuple[bool, str, float, float | None]:
    """
    Decide if an account should enter shutdown for lack of posts.

    Returns (should_shutdown, reason, idle_seconds, last_post_at).
    """
    from core.send_stats import count_since_cutoff, get_last_post_timestamp
    from core.group_send_stats import count_group_sends_since_cutoff
    from core.stats_reset import get_effective_cutoff

    now = now or time.time()
    if not account_expected_to_post(slot, worker_state):
        return False, "", 0.0, None

    last_post = get_last_post_timestamp(slot)
    started_at = float(getattr(worker_state, "worker_started_at", 0.0) or 0.0)
    running = bool(getattr(worker_state, "running", False))

    # Do not use pre-start post timestamps: fresh Start All at 11:23 must not
    # inherit yesterday's last_post and instantly hit the 6h shutdown rule.
    reference: float | None = last_post
    if running and started_at > 0:
        if reference is None or started_at > reference:
            reference = started_at

    if reference is not None:
        idle = now - reference
        if idle >= NO_POST_THRESHOLD_SECONDS:
            hours = int(idle // 3600)
            if last_post is None or (running and started_at > (last_post or 0)):
                return True, f"no_post_ever_{hours}h", idle, last_post
            return True, f"no_post_{hours}h", idle, last_post
        return False, "", idle, last_post

    cutoff = get_effective_cutoff(slot, now)
    if running and started_at > 0:
        cutoff = max(cutoff, started_at)
    window_idle = now - cutoff
    if window_idle < NO_POST_THRESHOLD_SECONDS:
        return False, "", window_idle, None

    forwards = count_since_cutoff(slot, cutoff)
    group_sends = count_group_sends_since_cutoff(slot, cutoff)
    if forwards == 0 and group_sends == 0:
        hours = int(window_idle // 3600)
        return True, f"no_post_since_reset_{hours}h", window_idle, None

    return False, "", window_idle, None
