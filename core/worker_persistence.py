"""
Persist which account workers were running before a process reload.
Used to auto-resume after uvicorn/PM2 restarts — no manual Start click.
"""

import json
import os
import time
from typing import List

from core.config import ACCOUNTS, DATA_DIR

RUNNING_FILE = os.path.join(DATA_DIR, ".running_workers.json")
RELOAD_LOG = os.path.join(DATA_DIR, "reload.log")
RESTART_COUNT_FILE = os.path.join(DATA_DIR, ".restart_count.json")


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def load_running_slots() -> List[str]:
    _ensure_data_dir()
    if not os.path.exists(RUNNING_FILE):
        return []
    try:
        with open(RUNNING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [s for s in data if s in ACCOUNTS]
    except Exception:
        pass
    return []


def save_running_slots(slots: List[str]) -> None:
    _ensure_data_dir()
    valid = [s for s in slots if s in ACCOUNTS]
    with open(RUNNING_FILE, "w", encoding="utf-8") as f:
        json.dump(valid, f, indent=2)


def mark_running(slot: str) -> None:
    slots = set(load_running_slots())
    slots.add(slot)
    save_running_slots(sorted(slots))


def mark_stopped(slot: str) -> None:
    slots = set(load_running_slots())
    slots.discard(slot)
    save_running_slots(sorted(slots))


def clear_all() -> None:
    save_running_slots([])


def bump_restart_count() -> int:
    """Monotonic restart counter persisted across process exits."""
    _ensure_data_dir()
    count = 0
    try:
        if os.path.exists(RESTART_COUNT_FILE):
            with open(RESTART_COUNT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                count = int(data.get("count", 0) or 0)
    except Exception:
        pass
    count += 1
    try:
        with open(RESTART_COUNT_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"count": count, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                f,
                indent=2,
            )
    except Exception:
        pass
    return count


def get_restart_count() -> int:
    try:
        if os.path.exists(RESTART_COUNT_FILE):
            with open(RESTART_COUNT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return int(data.get("count", 0) or 0)
    except Exception:
        pass
    return 0


def log_reload_event(reason: str) -> None:
    _ensure_data_dir()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} — {reason}\n"
    try:
        with open(RELOAD_LOG, "a", encoding="utf-8") as f:
            f.write(line)
        # Keep log bounded
        if os.path.getsize(RELOAD_LOG) > 256_000:
            with open(RELOAD_LOG, "r", encoding="utf-8") as f:
                tail = f.readlines()[-300:]
            with open(RELOAD_LOG, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except Exception:
        pass
