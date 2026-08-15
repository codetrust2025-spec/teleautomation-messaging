"""
Fleet-wide Telegram rate-limit awareness — coordinates slowdown across accounts.

Detects correlated flood events (API-wide pressure) and exposes a shared delay multiplier.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

FLEET_WINDOW_SECONDS = 300
FLEET_FLOOD_EVENT_TTL = 600
HIGH_PRESSURE_ACCOUNTS = 3
CRITICAL_PRESSURE_ACCOUNTS = 6


@dataclass
class _FloodEvent:
    account_id: str
    timestamp: float
    seconds: int


@dataclass
class FleetRateCoordinator:
    """Thread-safe global flood/event tracker for multi-account fleets."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _events: deque = field(default_factory=deque)
    _account_last_flood: dict[str, float] = field(default_factory=dict)

    def record_flood(self, account_id: str, *, seconds: int = 0) -> None:
        now = time.time()
        with self._lock:
            self._events.append(_FloodEvent(account_id, now, max(0, int(seconds))))
            self._account_last_flood[account_id] = now
            self._prune_unlocked(now)

    def _prune_unlocked(self, now: float) -> None:
        cutoff = now - FLEET_FLOOD_EVENT_TTL
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()

    def _recent_unique_accounts(self, window: float) -> set[str]:
        now = time.time()
        cutoff = now - window
        return {e.account_id for e in self._events if e.timestamp >= cutoff}

    def fleet_pressure(self) -> float:
        """
        0.0 = calm, 1.0 = heavy fleet-wide rate limiting.
        Based on distinct accounts hitting flood in the last 5 minutes.
        """
        n = len(self._recent_unique_accounts(FLEET_WINDOW_SECONDS))
        if n >= CRITICAL_PRESSURE_ACCOUNTS:
            return 1.0
        if n >= HIGH_PRESSURE_ACCOUNTS:
            return 0.65 + 0.05 * min(n - HIGH_PRESSURE_ACCOUNTS, 6)
        if n >= 2:
            return 0.25 + 0.1 * (n - 2)
        if n == 1:
            return 0.12
        return 0.0

    def delay_multiplier(self) -> float:
        """Fleet-wide delay scale factor (1.0 – 2.0)."""
        p = self.fleet_pressure()
        return 1.0 + p

    def should_stagger_account(self, account_id: str, slot_index: int) -> float:
        """
        Extra startup/cycle stagger seconds when fleet is under pressure.
        Spreads load across accounts (useful at 50+ scale).
        """
        p = self.fleet_pressure()
        if p < 0.2:
            return 0.0
        return min(30.0, slot_index * 0.4 * p)

    def account_recently_flooded(self, account_id: str, within: float = 120.0) -> bool:
        with self._lock:
            ts = self._account_last_flood.get(account_id)
        if not ts:
            return False
        return (time.time() - ts) < within

    def snapshot(self) -> dict:
        with self._lock:
            self._prune_unlocked(time.time())
            recent = self._recent_unique_accounts(FLEET_WINDOW_SECONDS)
        return {
            "pressure": round(self.fleet_pressure(), 3),
            "delay_multiplier": round(self.delay_multiplier(), 3),
            "flooded_accounts_5m": len(recent),
            "recent_flood_accounts": sorted(recent),
        }


fleet_rate_coordinator = FleetRateCoordinator()
