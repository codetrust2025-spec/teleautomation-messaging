"""In-memory TTL cache for master groups list — reduces per-cycle disk reads."""

from __future__ import annotations

import threading
import time
from typing import List

from core.group_assignment import groups_for_slot

_CACHE_TTL_SECONDS = 45.0
_lock = threading.Lock()
_master_cache: list[str] | None = None
_master_loaded_at: float = 0.0
_slot_cache: dict[str, tuple[float, list[str]]] = {}


def invalidate_master_cache() -> None:
    """Call after master groups file is written."""
    global _master_cache, _master_loaded_at
    with _lock:
        _master_cache = None
        _master_loaded_at = 0.0
        _slot_cache.clear()


def set_master_cache(groups: list[str]) -> None:
    """Seed cache after load or save."""
    global _master_cache, _master_loaded_at
    with _lock:
        _master_cache = list(groups)
        _master_loaded_at = time.time()
        _slot_cache.clear()


def get_cached_master(*, loader) -> list[str]:
    """Return cached master list or load via loader() and cache."""
    global _master_cache, _master_loaded_at
    now = time.time()
    with _lock:
        if _master_cache is not None and (now - _master_loaded_at) < _CACHE_TTL_SECONDS:
            return list(_master_cache)
    fresh = list(loader())
    with _lock:
        _master_cache = fresh
        _master_loaded_at = time.time()
        _slot_cache.clear()
    return list(fresh)


def get_cached_slice(slot: str, master: list[str]) -> list[str]:
    """Per-slot partition cached briefly alongside master refresh."""
    now = time.time()
    with _lock:
        entry = _slot_cache.get(slot)
        if entry and (now - entry[0]) < _CACHE_TTL_SECONDS:
            return list(entry[1])
    sliced = groups_for_slot(slot, master)
    with _lock:
        _slot_cache[slot] = (now, sliced)
    return list(sliced)
