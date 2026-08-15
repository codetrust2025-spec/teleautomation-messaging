"""
Forward Intelligence System - Adaptive learning for 10/10 forwarding performance.

Tracks FloodWait patterns, dead peers, and account health to optimize tick intervals,
prevent cascading rate limits, and maximize sustainable forwarding throughput.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from core.config import STATE_DIR

# Adaptive tick interval ranges based on recent FloodWait history
TICK_INTERVAL_RANGES = {
    "aggressive": (8 * 60, 15 * 60),      # 8-15 min (no recent floods)
    "normal": (10 * 60, 30 * 60),         # 10-30 min (default)
    "cautious": (20 * 60, 45 * 60),       # 20-45 min (1-2 recent floods)
    "conservative": (40 * 60, 90 * 60),   # 40-90 min (3+ recent floods)
    "cooldown": (120 * 60, 180 * 60),     # 2-3 hours (heavy flood detected)
}

# FloodWait severity thresholds
FLOOD_LIGHT = 60        # < 60s = light flood (ignorable)
FLOOD_MEDIUM = 300      # 60-300s = medium flood (slow down)
FLOOD_HEAVY = 3600      # 300-3600s = heavy flood (back off significantly)
FLOOD_CRITICAL = 86400  # > 1 day = critical (cooldown mode)

# Health score thresholds for throttling
HEALTH_EXCELLENT = 90
HEALTH_GOOD = 75
HEALTH_FAIR = 60
HEALTH_POOR = 40

# Dead peer cleanup settings
DEAD_PEER_CACHE_HOURS = 24
MAX_DEAD_PEER_AGE_DAYS = 7

# FloodWait history tracking
FLOOD_HISTORY_WINDOW_HOURS = 6
MAX_FLOOD_HISTORY_ENTRIES = 100


@dataclass
class FloodEvent:
    """Single FloodWait occurrence"""
    timestamp: float
    seconds: int
    group: str = ""

    def severity(self) -> str:
        if self.seconds < FLOOD_LIGHT:
            return "light"
        elif self.seconds < FLOOD_MEDIUM:
            return "medium"
        elif self.seconds < FLOOD_HEAVY:
            return "heavy"
        else:
            return "critical"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "seconds": self.seconds,
            "group": self.group,
            "severity": self.severity(),
        }


@dataclass
class DeadPeer:
    """Known invalid/blocked group"""
    peer: str
    reason: str
    first_seen: float
    last_seen: float
    failure_count: int = 1

    def is_expired(self, max_age_days: int = MAX_DEAD_PEER_AGE_DAYS) -> bool:
        return (time.time() - self.first_seen) > (max_age_days * 86400)

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer": self.peer,
            "reason": self.reason,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "failure_count": self.failure_count,
        }


@dataclass
class ForwardIntelligence:
    """Per-account forwarding intelligence state"""
    slot: str
    flood_history: list[FloodEvent] = field(default_factory=list)
    dead_peers: dict[str, DeadPeer] = field(default_factory=dict)
    last_tick_time: float = 0
    last_cleanup_time: float = 0
    total_ticks: int = 0
    successful_ticks: int = 0
    flooded_ticks: int = 0
    cooldown_until: float = 0

    def add_flood_event(self, seconds: int, group: str = "") -> None:
        """Record a FloodWait occurrence"""
        now = time.time()
        self.flood_history.append(FloodEvent(
            timestamp=now,
            seconds=seconds,
            group=group,
        ))

        # Trim old history
        cutoff = now - (FLOOD_HISTORY_WINDOW_HOURS * 3600)
        self.flood_history = [
            e for e in self.flood_history
            if e.timestamp > cutoff
        ][-MAX_FLOOD_HISTORY_ENTRIES:]

        # Set cooldown for critical floods
        if seconds >= FLOOD_CRITICAL:
            self.cooldown_until = now + (seconds * 1.5)  # Wait 1.5x the flood time

    def add_dead_peer(self, peer: str, reason: str) -> None:
        """Record a permanently failed target"""
        now = time.time()
        if peer in self.dead_peers:
            dp = self.dead_peers[peer]
            dp.last_seen = now
            dp.failure_count += 1
            dp.reason = reason  # Update to latest reason
        else:
            self.dead_peers[peer] = DeadPeer(
                peer=peer,
                reason=reason,
                first_seen=now,
                last_seen=now,
            )

    def cleanup_expired_dead_peers(self) -> int:
        """Remove old dead peer entries"""
        before_count = len(self.dead_peers)
        self.dead_peers = {
            k: v for k, v in self.dead_peers.items()
            if not v.is_expired()
        }
        self.last_cleanup_time = time.time()
        return before_count - len(self.dead_peers)

    def get_dead_peer_set(self) -> set[str]:
        """Get current set of dead peer identifiers"""
        # Cleanup if stale
        if time.time() - self.last_cleanup_time > (DEAD_PEER_CACHE_HOURS * 3600):
            self.cleanup_expired_dead_peers()
        return set(self.dead_peers.keys())

    def recent_flood_count(self, hours: int = 1) -> int:
        """Count FloodWaits in recent time window"""
        cutoff = time.time() - (hours * 3600)
        return sum(1 for e in self.flood_history if e.timestamp > cutoff)

    def recent_heavy_floods(self, hours: int = 1) -> int:
        """Count heavy/critical floods in recent window"""
        cutoff = time.time() - (hours * 3600)
        return sum(
            1 for e in self.flood_history
            if e.timestamp > cutoff and e.severity() in ("heavy", "critical")
        )

    def is_in_cooldown(self) -> bool:
        """Check if account is in enforced cooldown period"""
        return time.time() < self.cooldown_until

    def cooldown_remaining_seconds(self) -> int:
        """Seconds remaining in cooldown"""
        if not self.is_in_cooldown():
            return 0
        return int(self.cooldown_until - time.time())

    def recommend_tick_profile(self, health_score: float = 100.0) -> str:
        """Determine optimal tick interval profile based on state"""
        # Cooldown mode overrides everything
        if self.is_in_cooldown():
            return "cooldown"

        # Check recent flood activity
        floods_1h = self.recent_flood_count(hours=1)
        heavy_floods_6h = self.recent_heavy_floods(hours=6)

        # Health-based downgrade
        if health_score < HEALTH_POOR:
            return "conservative"

        # FloodWait pattern analysis
        if heavy_floods_6h >= 2:
            return "cooldown"
        elif floods_1h >= 3:
            return "conservative"
        elif floods_1h >= 2:
            return "cautious"
        elif floods_1h >= 1:
            return "normal"

        # Default: if health is excellent and no recent floods, be aggressive
        if health_score >= HEALTH_EXCELLENT and floods_1h == 0:
            return "aggressive"

        return "normal"

    def compute_next_tick_interval(self, health_score: float = 100.0) -> int:
        """Calculate optimal seconds until next tick"""
        import random

        profile = self.recommend_tick_profile(health_score)
        min_sec, max_sec = TICK_INTERVAL_RANGES[profile]

        # Add jitter for unpredictability
        base_interval = random.randint(min_sec, max_sec)
        jitter = random.randint(-30, 30)

        return max(60, base_interval + jitter)

    def should_skip_tick(self, health_score: float = 100.0) -> tuple[bool, str]:
        """Determine if this tick should be skipped entirely"""
        # Cooldown enforcement
        if self.is_in_cooldown():
            remaining = self.cooldown_remaining_seconds()
            return True, f"cooldown_active_{remaining}s"

        # Health-based skip
        if health_score < HEALTH_POOR:
            return True, f"health_too_low_{int(health_score)}"

        # Too many recent floods
        if self.recent_heavy_floods(hours=1) >= 2:
            return True, "too_many_heavy_floods"

        return False, "ok"

    def record_tick_start(self) -> None:
        """Mark beginning of a tick"""
        self.last_tick_time = time.time()
        self.total_ticks += 1

    def record_tick_success(self) -> None:
        """Mark successful tick completion"""
        self.successful_ticks += 1

    def record_tick_flooded(self) -> None:
        """Mark tick ended due to FloodWait"""
        self.flooded_ticks += 1

    def get_stats(self) -> dict[str, Any]:
        """Get intelligence statistics"""
        return {
            "total_ticks": self.total_ticks,
            "successful_ticks": self.successful_ticks,
            "flooded_ticks": self.flooded_ticks,
            "success_rate": (
                self.successful_ticks / self.total_ticks
                if self.total_ticks > 0 else 1.0
            ),
            "dead_peers_count": len(self.dead_peers),
            "floods_last_hour": self.recent_flood_count(hours=1),
            "floods_last_6h": self.recent_flood_count(hours=6),
            "heavy_floods_last_6h": self.recent_heavy_floods(hours=6),
            "in_cooldown": self.is_in_cooldown(),
            "cooldown_remaining_sec": self.cooldown_remaining_seconds(),
            "current_profile": self.recommend_tick_profile(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "flood_history": [e.to_dict() for e in self.flood_history],
            "dead_peers": {k: v.to_dict() for k, v in self.dead_peers.items()},
            "last_tick_time": self.last_tick_time,
            "last_cleanup_time": self.last_cleanup_time,
            "total_ticks": self.total_ticks,
            "successful_ticks": self.successful_ticks,
            "flooded_ticks": self.flooded_ticks,
            "cooldown_until": self.cooldown_until,
            "stats": self.get_stats(),
        }


def _intel_path(slot: str) -> str:
    """Path to per-account intelligence file"""
    os.makedirs(os.path.join(STATE_DIR, slot), exist_ok=True)
    return os.path.join(STATE_DIR, slot, "forward_intelligence.json")


def load_forward_intelligence(slot: str) -> ForwardIntelligence:
    """Load or create intelligence state"""
    path = _intel_path(slot)
    if not os.path.exists(path):
        return ForwardIntelligence(slot=slot)

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        # Reconstruct flood history
        flood_history = []
        for e in raw.get("flood_history", []):
            if isinstance(e, dict):
                flood_history.append(FloodEvent(
                    timestamp=float(e.get("timestamp", 0)),
                    seconds=int(e.get("seconds", 0)),
                    group=str(e.get("group", "")),
                ))

        # Reconstruct dead peers
        dead_peers = {}
        for k, v in raw.get("dead_peers", {}).items():
            if isinstance(v, dict):
                dead_peers[str(k)] = DeadPeer(
                    peer=str(v.get("peer", k)),
                    reason=str(v.get("reason", "unknown")),
                    first_seen=float(v.get("first_seen", time.time())),
                    last_seen=float(v.get("last_seen", time.time())),
                    failure_count=int(v.get("failure_count", 1)),
                )

        return ForwardIntelligence(
            slot=slot,
            flood_history=flood_history,
            dead_peers=dead_peers,
            last_tick_time=float(raw.get("last_tick_time", 0)),
            last_cleanup_time=float(raw.get("last_cleanup_time", 0)),
            total_ticks=int(raw.get("total_ticks", 0)),
            successful_ticks=int(raw.get("successful_ticks", 0)),
            flooded_ticks=int(raw.get("flooded_ticks", 0)),
            cooldown_until=float(raw.get("cooldown_until", 0)),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        return ForwardIntelligence(slot=slot)


def save_forward_intelligence(intel: ForwardIntelligence) -> None:
    """Persist intelligence state"""
    path = _intel_path(intel.slot)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(intel.to_dict(), f, indent=2)
    os.replace(tmp, path)


def record_forward_flood(slot: str, seconds: int, group: str = "") -> None:
    """Convenience function to record FloodWait"""
    intel = load_forward_intelligence(slot)
    intel.add_flood_event(seconds, group)
    save_forward_intelligence(intel)


def record_forward_dead_peer(slot: str, peer: str, reason: str) -> None:
    """Convenience function to record dead peer"""
    intel = load_forward_intelligence(slot)
    intel.add_dead_peer(peer, reason)
    save_forward_intelligence(intel)


def get_forward_dead_peers(slot: str) -> set[str]:
    """Get current dead peer set for filtering"""
    intel = load_forward_intelligence(slot)
    return intel.get_dead_peer_set()


def compute_adaptive_tick_interval(slot: str, health_score: float = 100.0) -> int:
    """Compute next tick interval with adaptive learning"""
    intel = load_forward_intelligence(slot)
    return intel.compute_next_tick_interval(health_score)


def should_skip_forward_tick(slot: str, health_score: float = 100.0) -> tuple[bool, str]:
    """Check if tick should be skipped"""
    intel = load_forward_intelligence(slot)
    return intel.should_skip_tick(health_score)
