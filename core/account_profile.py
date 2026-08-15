"""
Per-account behavior profiles — optional tuning without hardcoding UI.

account7: balanced / slightly slower (more delay between actions)
account8: safe / conservative (higher delays, fewer joins per day)
"""

from __future__ import annotations

from typing import Any

_DEFAULT_PROFILE: dict[str, Any] = {
    "label": "default",
    "delay_base_mult": 1.0,
    "join_daily_limit": None,  # use global JOIN_DAILY_LIMIT
    "join_recent_max": None,
}

ACCOUNT_PROFILES: dict[str, dict[str, Any]] = {
    "account7": {
        "label": "balanced",
        "delay_base_mult": 1.15,
        "join_daily_limit": 12,
        "join_recent_max": 3,
        "description": "Slower, balanced pacing",
    },
    "account8": {
        "label": "safe",
        "delay_base_mult": 1.35,
        "join_daily_limit": 8,
        "join_recent_max": 2,
        "description": "Conservative / fallback — safest limits",
    },
}


def get_account_profile(slot: str) -> dict[str, Any]:
    base = dict(_DEFAULT_PROFILE)
    extra = ACCOUNT_PROFILES.get(slot) or {}
    base.update(extra)
    return base


def get_delay_base_multiplier(slot: str) -> float:
    return float(get_account_profile(slot).get("delay_base_mult") or 1.0)


def get_join_daily_limit(slot: str) -> int:
    from core.config import JOIN_DAILY_LIMIT

    custom = get_account_profile(slot).get("join_daily_limit")
    if custom is not None:
        return int(custom)
    return JOIN_DAILY_LIMIT


def get_join_recent_max(slot: str) -> int:
    from core.config import JOIN_RECENT_MAX

    custom = get_account_profile(slot).get("join_recent_max")
    if custom is not None:
        return int(custom)
    return JOIN_RECENT_MAX


def apply_profile_to_intel(intel) -> None:
    """Apply profile base delay after intelligence loads from disk."""
    prof = get_account_profile(intel.slot)
    acct = intel.account_meta
    acct["profile"] = prof.get("label", "default")
    base_mult = float(prof.get("delay_base_mult") or 1.0)
    health_mult = float(acct.get("delay_multiplier") or 1.0)
    acct["delay_multiplier"] = round(max(health_mult, base_mult), 2)
