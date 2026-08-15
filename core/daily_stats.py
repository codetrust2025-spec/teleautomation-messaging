"""Aggregate daily / since-reset stats from inbox messages and forward send history."""

from __future__ import annotations

from datetime import datetime, timezone

from core.dm_store import load_inbox
from core.send_stats import (
    count_since_cutoff,
    hourly_bucket_labels,
    hourly_buckets,
)
from core.stats_reset import (
    get_effective_cutoff,
    get_reset_at_iso,
    active_reset_timestamp,
    stats_window_kind,
)
from core.ist_time import APP_TIMEZONE, ist_day_start_iso, ist_day_start_ts


def _parse_iso_ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        s = str(iso).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def _empty_slot_stats() -> dict:
    return {
        "contacts": 0,
        "incoming": 0,
        "outgoing": 0,
        "forwarded": 0,
        "campaign_posts": 0,
        "forward_posts": 0,
    }


def _posting_mode_kind(slot: str) -> str:
    """Return forward, campaign, or mixed for legacy send attribution."""
    try:
        from core.posting_mode import load_posting_mode

        pm = load_posting_mode(slot)
        if pm.forwarding_enabled and not pm.campaign_enabled:
            return "forward"
        if pm.campaign_enabled and not pm.forwarding_enabled:
            return "campaign"
    except Exception:
        pass
    return "mixed"


def _legacy_unsplit(slot: str, cutoff: float) -> bool:
    """True when sends exist only in legacy send_history.json (no mode split)."""
    total = count_since_cutoff(slot, cutoff)
    if total <= 0:
        return False
    return (
        count_since_cutoff(slot, cutoff, "forward") == 0
        and count_since_cutoff(slot, cutoff, "campaign") == 0
    )


def _apply_legacy_send_split(slot: str, stats: dict) -> dict:
    """Attribute legacy-only totals to the account's active posting mode."""
    forward_posts = int(stats.get("forward_posts") or 0)
    campaign_posts = int(stats.get("campaign_posts") or 0)
    forwarded = int(stats.get("forwarded") or 0)
    if forward_posts or campaign_posts or not forwarded:
        return stats
    kind = _posting_mode_kind(slot)
    out = dict(stats)
    if kind == "forward":
        out["forward_posts"] = forwarded
    elif kind == "campaign":
        out["campaign_posts"] = forwarded
    return out


def _hourly_for_mode(slots: list[str], mode: str, bucket_count: int = 24) -> list[int]:
    """Hourly buckets for a mode, falling back to legacy history when mode files are empty."""
    buckets = hourly_buckets(slots, mode=mode, bucket_count=bucket_count)
    if sum(buckets) > 0:
        return buckets
    out = [0] * bucket_count
    found = False
    for slot in slots:
        cutoff = get_effective_cutoff(slot)
        if not _legacy_unsplit(slot, cutoff):
            continue
        kind = _posting_mode_kind(slot)
        if mode == "forward" and kind != "forward":
            continue
        if mode == "campaign" and kind != "campaign":
            continue
        slot_buckets = hourly_buckets([slot], mode=None, bucket_count=bucket_count)
        for i, value in enumerate(slot_buckets):
            out[i] += value
        found = True
    return out if found else buckets


def stats_for_inbox_slot(slot: str, cutoff: float) -> dict:
    """DM inbox counts since cutoff (raw messages kept on disk)."""
    contacts: set[int] = set()
    incoming = 0
    outgoing = 0

    data = load_inbox(slot)
    for conv in (data.get("conversations") or {}).values():
        uid = conv.get("user_id")
        for msg in conv.get("messages") or []:
            ts = _parse_iso_ts(msg.get("timestamp"))
            if ts is None or ts < cutoff:
                continue
            direction = msg.get("direction")
            if direction == "in":
                incoming += 1
                if uid is not None:
                    contacts.add(int(uid))
            elif direction == "out":
                st = msg.get("status") or ""
                if st == "sending":
                    continue
                outgoing += 1
                if uid is not None:
                    contacts.add(int(uid))

    campaign_posts = count_since_cutoff(slot, cutoff, "campaign")
    forward_posts = count_since_cutoff(slot, cutoff, "forward")
    return {
        "contacts": len(contacts),
        "incoming": incoming,
        "outgoing": outgoing,
        "forwarded": campaign_posts + forward_posts,
        "campaign_posts": campaign_posts,
        "forward_posts": forward_posts,
    }
    return _apply_legacy_send_split(slot, stats)


def _sum_slots(per_slot: dict) -> dict:
    total = _empty_slot_stats()
    for row in per_slot.values():
        for key in total:
            total[key] += int(row.get(key) or 0)
    return total


def refresh_daily_stats(slots: list[str]) -> tuple[dict, object | None]:
    """Apply automatic 24h rollover if due, then compute dashboard stats."""
    from core.stats_reset import maybe_auto_reset_24h

    auto = maybe_auto_reset_24h(slots)
    return compute_daily_stats(slots), auto


def compute_daily_stats(slots: list[str]) -> dict:
    window = stats_window_kind()
    manual_reset = active_reset_timestamp()
    day_start = ist_day_start_ts()
    per_slot = {
        slot: stats_for_inbox_slot(slot, get_effective_cutoff(slot))
        for slot in slots
    }
    global_stats = _sum_slots(per_slot)
    crm_stats = {}
    try:
        from services.crm_service import compute_crm_stats

        crm_stats = compute_crm_stats()
    except Exception:
        pass

    return {
        "window": window,
        "timezone": APP_TIMEZONE,
        "reset_timestamp": manual_reset,
        "reset_at": get_reset_at_iso() if manual_reset else ist_day_start_iso(),
        "cutoff_timestamp": get_effective_cutoff(),
        "day_start_timestamp": day_start,
        "global": global_stats,
        "per_account": per_slot,
        "crm": crm_stats,
        "hourly": {
            "bucket_count": 24,
            "bucket_seconds": 3600,
            "labels": hourly_bucket_labels(24),
            "sent": {
                "all": hourly_buckets(slots, mode=None),
                "forward": _hourly_for_mode(slots, "forward"),
                "campaign": _hourly_for_mode(slots, "campaign"),
            },
        },
    }
