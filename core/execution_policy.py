"""
Self-optimizing execution policy — derives delays and activity flags from live metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.cycle_metrics import cycle_metrics_store
from core.config import SPEED_FAST_SUCCESS_RATE


@dataclass
class ExecutionPolicy:
    account_id: str
    send_delay_multiplier: float = 1.0
    cycle_delay_multiplier: float = 1.0
    min_groups_before_dm_yield: int = 3
    max_dm_yield_ms: int = 2000
    max_cycle_wall_seconds: int = 5400
    unhealthy: bool = False
    pause_recommended: bool = False
    fleet_pressure: float = 0.0
    reasons: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "send_delay_multiplier": round(self.send_delay_multiplier, 3),
            "cycle_delay_multiplier": round(self.cycle_delay_multiplier, 3),
            "min_groups_before_dm_yield": self.min_groups_before_dm_yield,
            "max_dm_yield_ms": self.max_dm_yield_ms,
            "max_cycle_wall_seconds": self.max_cycle_wall_seconds,
            "unhealthy": self.unhealthy,
            "pause_recommended": self.pause_recommended,
            "fleet_pressure": round(self.fleet_pressure, 3),
            "reasons": list(self.reasons or []),
        }


def _avg_success_rate(history: list[dict]) -> float | None:
    rates = [h.get("success_rate") for h in history if h.get("success_rate") is not None]
    if not rates:
        return None
    return sum(float(r) for r in rates) / len(rates)


def _early_exit_rate(history: list[dict]) -> float:
    if not history:
        return 0.0
    early = sum(1 for h in history if h.get("ended_early"))
    return early / len(history)


def compute_execution_policy(
    account_id: str,
    *,
    health_score: float,
    heavy_rate_limit: bool,
    flood_streak: int = 0,
    fleet_pressure: float = 0.0,
    fleet_delay_multiplier: float = 1.0,
    recently_flooded: bool = False,
) -> ExecutionPolicy:
    """Build adaptive policy from account-local metrics.

    Fleet signals are optional and injected by the runtime. The default path
    is fully account-local, so one account cannot slow another.
    """
    history = cycle_metrics_store.history(account_id, limit=5)
    latest = cycle_metrics_store.latest(account_id)
    fleet_p = max(0.0, float(fleet_pressure or 0.0))
    fleet_mult = max(0.1, float(fleet_delay_multiplier or 1.0))

    send_mult = fleet_mult
    cycle_mult = fleet_mult
    reasons: list[str] = []
    unhealthy = False
    pause_recommended = heavy_rate_limit
    min_groups = 3
    max_yield_ms = 2000
    max_wall = 5400

    avg_sr = _avg_success_rate(history)
    if avg_sr is not None:
        if avg_sr >= 88:
            send_mult *= 0.92
            cycle_mult *= 0.9
            reasons.append("high_success_rate")
        elif avg_sr >= SPEED_FAST_SUCCESS_RATE:
            send_mult *= 0.88
            cycle_mult *= 0.85
            reasons.append("speed_eligible_success")
        elif avg_sr < 45:
            send_mult *= 1.25
            cycle_mult *= 1.2
            unhealthy = True
            reasons.append("low_success_rate")
        elif avg_sr < 60:
            send_mult *= 1.1
            reasons.append("moderate_success_rate")

    if health_score < 40:
        send_mult *= 1.35
        cycle_mult *= 1.25
        unhealthy = True
        pause_recommended = True
        reasons.append("health_critical")
    elif health_score < 55:
        send_mult *= 1.15
        reasons.append("health_low")

    if flood_streak >= 2:
        send_mult *= 1.0 + 0.15 * min(flood_streak, 4)
        reasons.append("flood_streak")

    if fleet_p >= 0.65:
        min_groups = 5
        max_yield_ms = 800
        cycle_mult *= 1.1
        reasons.append("fleet_high_pressure")
    elif fleet_p >= 0.25:
        min_groups = 4
        max_yield_ms = 1200
        reasons.append("fleet_elevated_pressure")

    early_rate = _early_exit_rate(history)
    if early_rate >= 0.6 and len(history) >= 3:
        unhealthy = True
        pause_recommended = True
        reasons.append("frequent_early_cycle_exit")

    if latest and latest.get("end_reason") in ("flood_break", "session_break"):
        send_mult *= 1.08
        cycle_mult *= 1.05
        reasons.append("last_cycle_interrupted")
    elif latest and latest.get("end_reason") == "complete":
        sr = float(latest.get("success_rate") or 0)
        if sr >= 85:
            cycle_mult *= 0.88
            send_mult *= 0.92
            reasons.append("last_cycle_high_success")
        gps = float(latest.get("groups_per_second") or 0)
        if gps >= 0.06:
            cycle_mult *= 0.92
            reasons.append("last_cycle_throughput_ok")

    if recently_flooded:
        send_mult *= 1.12
        reasons.append("recent_account_flood")

    return ExecutionPolicy(
        account_id=account_id,
        send_delay_multiplier=max(0.55, min(send_mult, 2.5)),
        cycle_delay_multiplier=max(0.55, min(cycle_mult, 2.5)),
        min_groups_before_dm_yield=min_groups,
        max_dm_yield_ms=max_yield_ms,
        max_cycle_wall_seconds=max_wall,
        unhealthy=unhealthy,
        pause_recommended=pause_recommended,
        fleet_pressure=fleet_p,
        reasons=reasons,
    )
