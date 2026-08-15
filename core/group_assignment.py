"""
Evenly distribute master groups across account slots (load balancing).

Each account only processes its slice — independent cycles, no overlap.
Add accounts in config → slice size adjusts automatically.

By default the partition is restricted to **logged-in** accounts so master
groups owned by a logged-out slot are not stranded. When no account is logged
in we fall back to the full slot list to keep behavior stable for tests/UI.
"""

from __future__ import annotations

import os

from core.config import ACCOUNT_SLOTS, STATE_DIR


def slot_index(slot: str) -> int:
    try:
        return ACCOUNT_SLOTS.index(slot)
    except ValueError:
        return 0


def account_count() -> int:
    return max(1, len(ACCOUNT_SLOTS))


def _slot_logged_in(slot: str) -> bool:
    return os.path.exists(os.path.join(STATE_DIR, slot, "account_info.json"))


def active_slots() -> list[str]:
    """Slots that currently have a saved login (account_info.json on disk)."""
    return [s for s in ACCOUNT_SLOTS if _slot_logged_in(s)]


def _partition_slots(*, include_slot: str | None = None) -> list[str]:
    """Slots used for round-robin partitioning. Falls back to all slots when
    none are logged in so empty deployments still get a deterministic split."""
    actives = active_slots()
    if include_slot and include_slot not in actives:
        # Caller is asking about a slot that isn't logged in — just include it
        # so the legacy slot ordering is preserved for that single query.
        actives = sorted(set(actives) | {include_slot}, key=lambda s: slot_index(s))
    return actives or list(ACCOUNT_SLOTS)


def groups_for_slot(slot: str, master: list[str]) -> list[str]:
    """
    Round-robin partition over **logged-in** accounts only.
    Logged-out accounts get an empty slice so their share is not stranded.
    """
    if not master:
        return []
    if not _slot_logged_in(slot):
        return []
    parts = _partition_slots()
    if slot not in parts:
        return []
    n = max(1, len(parts))
    idx = parts.index(slot)
    return [g for i, g in enumerate(master) if i % n == idx]


def partition_summary(slot: str, master: list[str]) -> dict:
    parts = _partition_slots(include_slot=slot)
    assigned = groups_for_slot(slot, master)
    return {
        "slot": slot,
        "slot_index": (parts.index(slot) + 1) if slot in parts else 0,
        "account_count": len(parts),
        "total_master": len(master),
        "assigned_count": len(assigned),
        "share_pct": round(len(assigned) / len(master) * 100, 1) if master else 0,
        "logged_in_accounts": len(active_slots()),
    }
