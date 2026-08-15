"""
Unified Action Scheduler — per-group send / join / skip decisions.

Hard join limits (evaluate_join) are never bypassed. Adaptive logic chooses when
joins are worthwhile; speed comes from skipping bad work and tiered delays.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.config import (
    HEALTH_GOOD_THRESHOLD,
    HEALTH_MEDIUM_THRESHOLD,
    JOIN_DAILY_LIMIT,
    JOIN_MIN_INTERVAL_SECONDS,
    JOIN_MIN_SCORE_FOR_TRY,
    JOIN_PRIORITY_SCORE,
    JOIN_RECENT_MAX,
    PRE_JOIN_MIN_SCORE,
    PRE_JOIN_PROBABILITY,
    UAS_DAILY_HEADROOM_FLOOR,
    UAS_JOIN_SUCCESS_MIN_RATE,
    UAS_MIN_JOIN_ATTEMPTS_FOR_RATE,
)
from core.join_cycle import evaluate_join, load_join_state


class Action(str, Enum):
    SKIP = "skip"
    SEND = "send"
    JOIN_THEN_SEND = "join_then_send"
    PRE_JOIN = "pre_join"


@dataclass
class SchedulerDecision:
    action: Action
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action.value, "reason": self.reason}


@dataclass
class SchedulerContext:
    """Mutable per-cycle scheduler state."""

    account_id: str
    health_score: float
    success_rate: float | None
    flood_streak: int
    cycles_without_flood: int
    fleet_pressure: float
    unhealthy: bool
    heavy_rate_limit: bool
    speed_mode: str  # fast | normal | cautious
    max_joins_per_cycle: int = 0
    min_groups_between_joins: int = 12
    proactive_join_enabled: bool = False
    joins_this_cycle: int = 0
    groups_since_last_join: int = 0
    groups_processed_this_cycle: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "health_score": round(self.health_score, 1),
            "success_rate": self.success_rate,
            "speed_mode": self.speed_mode,
            "max_joins_per_cycle": self.max_joins_per_cycle,
            "min_groups_between_joins": self.min_groups_between_joins,
            "proactive_join_enabled": self.proactive_join_enabled,
            "joins_this_cycle": self.joins_this_cycle,
            "groups_since_last_join": self.groups_since_last_join,
            "groups_processed_this_cycle": self.groups_processed_this_cycle,
            "reasons": list(self.reasons),
        }

    def on_join_completed(self) -> None:
        self.joins_this_cycle += 1
        self.groups_since_last_join = 0

    def on_group_step(self) -> None:
        self.groups_since_last_join += 1
        self.groups_processed_this_cycle += 1


def _daily_headroom(slot: str) -> float:
    from core.account_profile import get_join_daily_limit

    state = load_join_state(slot)
    limit = get_join_daily_limit(slot) or JOIN_DAILY_LIMIT
    used = int(state.get("daily_new_joins") or 0)
    if limit <= 0:
        return 0.0
    return max(0.0, (limit - used) / limit)


def _burst_headroom(slot: str) -> float:
    from core.account_profile import get_join_recent_max

    state = load_join_state(slot)
    recent_max = get_join_recent_max(slot) or JOIN_RECENT_MAX
    raw = state.get("recent_new_join_ts") or []
    now = __import__("time").time()
    window = 7200
    count = sum(
        1
        for item in raw
        if (item if isinstance(item, (int, float)) else 0)
        and now - float(item if isinstance(item, (int, float)) else 0) < window
    )
    if recent_max <= 0:
        return 0.0
    return max(0.0, (recent_max - count) / recent_max)


def build_scheduler_context(
    account_id: str,
    *,
    health_score: float,
    success_rate: float | None,
    flood_streak: int,
    cycles_without_flood: int,
    fleet_pressure: float,
    unhealthy: bool,
    heavy_rate_limit: bool,
    speed_mode: str,
) -> SchedulerContext:
    from core.throughput_engine import adaptive_join_budget

    reasons: list[str] = []
    max_joins, min_between, proactive = adaptive_join_budget(
        health_score=health_score,
        speed_mode=speed_mode,
        success_rate=success_rate,
        fleet_pressure=fleet_pressure,
        heavy_rate_limit=heavy_rate_limit,
        unhealthy=unhealthy,
    )
    reasons.append(f"join_budget_{max_joins}_per_cycle")

    if fleet_pressure >= 0.5:
        max_joins = 0
        proactive = False
        reasons.append("fleet_pressure")

    if proactive:
        reasons.append("proactive_join_enabled")

    return SchedulerContext(
        account_id=account_id,
        health_score=health_score,
        success_rate=success_rate,
        flood_streak=flood_streak,
        cycles_without_flood=cycles_without_flood,
        fleet_pressure=fleet_pressure,
        unhealthy=unhealthy,
        heavy_rate_limit=heavy_rate_limit,
        speed_mode=speed_mode,
        max_joins_per_cycle=max_joins,
        min_groups_between_joins=min_between,
        proactive_join_enabled=proactive,
        reasons=reasons,
    )


def _join_soft_allowed(group: str, slot: str, intel, ctx: SchedulerContext) -> tuple[bool, str]:
    """Adaptive join signals — always after hard evaluate_join passes."""
    hard = evaluate_join(slot, group)
    if not hard.allowed:
        return False, hard.reason

    score = intel.get_score(group)
    if score < JOIN_MIN_SCORE_FOR_TRY:
        return False, "low_score"

    attempts = intel.get_join_attempts(group)
    success_rate = intel.get_join_success_rate(group)
    if attempts >= UAS_MIN_JOIN_ATTEMPTS_FOR_RATE and success_rate < UAS_JOIN_SUCCESS_MIN_RATE:
        return False, "low_join_success_rate"

    if ctx.health_score < HEALTH_MEDIUM_THRESHOLD:
        return False, "health_low"
    if ctx.flood_streak > 0:
        return False, "flood_streak"
    if ctx.fleet_pressure >= 0.35:
        return False, "fleet_elevated"
    if ctx.unhealthy:
        return False, "unhealthy"

    if _daily_headroom(slot) < UAS_DAILY_HEADROOM_FLOOR:
        return False, "daily_budget_low"

    return True, "ok"


def should_pre_join(group: str, slot: str, intel, ctx: SchedulerContext) -> bool:
    if not ctx.proactive_join_enabled:
        return False
    if ctx.joins_this_cycle >= ctx.max_joins_per_cycle:
        return False
    if ctx.groups_since_last_join < ctx.min_groups_between_joins:
        return False
    if intel.get_membership_hint(group) == "member":
        return False
    if intel.get_score(group) < PRE_JOIN_MIN_SCORE:
        return False
    if _daily_headroom(slot) < 0.3:
        return False
    ok, _ = _join_soft_allowed(group, slot, intel, ctx)
    if not ok:
        return False
    return random.random() < PRE_JOIN_PROBABILITY


def decide(group: str, ctx: SchedulerContext, intel) -> SchedulerDecision:
    """Per-group action before any Telegram API call."""
    from core.throughput_engine import should_smart_pre_join

    slot = ctx.account_id

    if ctx.heavy_rate_limit:
        return SchedulerDecision(Action.SKIP, "account_sleeping")

    skip = intel.precheck_skip_reason(group, account_sleeping=False)
    if skip:
        return SchedulerDecision(Action.SKIP, skip)

    membership = intel.get_membership_hint(group)
    score = intel.get_score(group)
    last = intel.get_last_result(group)

    if membership == "member" or last in ("sent", "joined_sent", "ok"):
        return SchedulerDecision(Action.SEND, "member_or_prior_send")

    if should_smart_pre_join(group, slot, intel, ctx, score=score):
        return SchedulerDecision(Action.PRE_JOIN, "proactive_high_score")

    join_budget_ok = (
        ctx.joins_this_cycle < ctx.max_joins_per_cycle
        and ctx.groups_since_last_join >= ctx.min_groups_between_joins
    )

    if join_budget_ok and membership == "not_member":
        ok, reason = _join_soft_allowed(group, slot, intel, ctx)
        if ok and score >= JOIN_PRIORITY_SCORE:
            return SchedulerDecision(Action.JOIN_THEN_SEND, "not_member_high_score")

    if join_budget_ok:
        ok, reason = _join_soft_allowed(group, slot, intel, ctx)
        if ok and score >= JOIN_MIN_SCORE_FOR_TRY:
            return SchedulerDecision(Action.JOIN_THEN_SEND, f"adaptive_join_{reason}")

    if score >= JOIN_MIN_SCORE_FOR_TRY or membership != "not_member":
        return SchedulerDecision(Action.SEND, "send_first_discover")

    return SchedulerDecision(Action.SKIP, "low_score_skip")


def post_join_delay_seconds(
    *,
    health_score: float,
    speed_mode: str = "normal",
    success_rate: float | None = None,
) -> float:
    """Health-tier post-join delay before first message."""
    from core.throughput_engine import adaptive_post_join_delay

    return adaptive_post_join_delay(
        health_score=health_score,
        speed_mode=speed_mode,
        success_rate=success_rate,
    )
