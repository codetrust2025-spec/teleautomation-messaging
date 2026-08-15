"""Per-group successful forward counts per account (rolling 24h / since-reset)."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

from core.config import STATE_DIR
from core.stats_reset import get_effective_cutoff, get_reset_at_iso, get_reset_timestamp

_lock = threading.Lock()
_RETAIN_SECONDS = 86400 * 8  # keep a little extra for pruning


def _path(slot: str) -> str:
    os.makedirs(os.path.join(STATE_DIR, slot), exist_ok=True)
    return os.path.join(STATE_DIR, slot, "group_send_history.json")


def _load_events(slot: str) -> list[dict]:
    path = _path(slot)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            return [e for e in data["events"] if isinstance(e, dict)]
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict)]
    except Exception:
        pass
    return []


def _save_events(slot: str, events: list[dict]) -> None:
    try:
        with open(_path(slot), "w", encoding="utf-8") as f:
            json.dump({"events": events}, f, indent=0)
    except Exception:
        pass


def _normalize_group(group: str) -> str:
    g = (group or "").strip()
    if not g:
        return ""
    if not g.startswith("@"):
        return f"@{g.lstrip('@')}"
    return g


def record_group_send(slot: str, group: str) -> None:
    """Record one successful group forward for matrix stats."""
    if not slot:
        return
    g = _normalize_group(group)
    if not g:
        return
    now = time.time()
    with _lock:
        events = _load_events(slot)
        prune_before = now - _RETAIN_SECONDS
        events = [e for e in events if float(e.get("t") or 0) >= prune_before]
        events.append({"g": g, "t": now})
        _save_events(slot, events)


def get_last_group_send_timestamp(slot: str) -> float | None:
    events = _load_events(slot)
    if not events:
        return None
    try:
        return max(float(e.get("t") or 0) for e in events)
    except (TypeError, ValueError):
        return None


def count_group_sends_since_cutoff(slot: str, cutoff: float) -> int:
    if not slot:
        return 0
    return sum(1 for e in _load_events(slot) if float(e.get("t") or 0) >= cutoff)


def invalidate_cache(_slot: str | None = None) -> None:
    """Stats reset uses cutoff — no cache to clear. Kept for symmetry with send_stats."""
    return


def compute_group_send_matrix(slots: list[str]) -> dict:
    """Build account × group send counts since effective cutoff per account."""
    now = time.time()
    reset_ts = get_reset_timestamp()
    window = "since_reset" if reset_ts else "rolling_24h"

    per_slot_events: dict[str, list[dict]] = {}
    for slot in slots:
        cutoff = get_effective_cutoff(slot, now)
        raw = _load_events(slot)
        per_slot_events[slot] = [
            e for e in raw
            if float(e.get("t") or 0) >= cutoff and (e.get("g") or "").strip()
        ]

    group_index: dict[str, dict] = {}
    totals_by_account: dict[str, int] = {slot: 0 for slot in slots}

    for slot, events in per_slot_events.items():
        for ev in events:
            g = str(ev.get("g") or "").strip()
            if not g:
                continue
            row = group_index.setdefault(
                g,
                {"group": g, "counts": {s: 0 for s in slots}, "last_ts": 0.0},
            )
            row["counts"][slot] = int(row["counts"].get(slot) or 0) + 1
            totals_by_account[slot] = int(totals_by_account.get(slot) or 0) + 1
            ts = float(ev.get("t") or 0)
            if ts > float(row.get("last_ts") or 0):
                row["last_ts"] = ts

    rows = []
    for g, row in group_index.items():
        counts = row["counts"]
        total = sum(int(counts.get(s) or 0) for s in slots)
        last_ts = float(row.get("last_ts") or 0)
        last_iso = (
            datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()
            if last_ts > 0
            else None
        )
        rows.append({
            "group": g,
            "counts": counts,
            "total": total,
            "last_sent_at": last_iso,
        })

    rows.sort(key=lambda r: (-int(r.get("total") or 0), str(r.get("group") or "")))

    return {
        "window": window,
        "reset_timestamp": reset_ts,
        "reset_at": get_reset_at_iso(),
        "cutoff_timestamp": get_effective_cutoff(None, now),
        "slots": list(slots),
        "rows": rows,
        "totals_by_account": totals_by_account,
        "grand_total": sum(int(v) for v in totals_by_account.values()),
        "groups_with_sends": len(rows),
    }
