"""
Throughput-adaptive cycle tuning — ~2× speed for healthy accounts, auto-brake on flood/low success.

Composes with speed_optimizer + execution_policy + unified_scheduler.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from core.config import (
    HEALTH_GOOD_THRESHOLD,
    HEALTH_MEDIUM_THRESHOLD,
    POST_JOIN_DELAY_GOOD_MAX,
    POST_JOIN_DELAY_GOOD_MIN,
    POST_JOIN_DELAY_LOW_MAX,
    POST_JOIN_DELAY_LOW_MIN,
    POST_JOIN_DELAY_MED_MAX,
    POST_JOIN_DELAY_MED_MIN,
    PRE_JOIN_MIN_SCORE,
    SKIP_DELAY_FAST_MAX_SECONDS,
    SKIP_DELAY_FAST_MIN_SECONDS,
    SKIP_DELAY_MAX_SECONDS,
    SKIP_DELAY_MIN_SECONDS,
    SPEED_FAST_SUCCESS_RATE,
)

if TYPE_CHECKING:
    from core.smart_engine import GroupIntelligence
    from core.speed_optimizer import SpeedProfile


def throughput_multipliers(
    *,
    health_score: float,
    cycle_success_rate: float | None,
    avg_success_rate: float | None,
    flood_streak: int,
    cycles_without_flood: int,
    last_cycle: dict[str, Any] | None,
) -> tuple[float, float, list[str]]:
    """
    Feedback multipliers for send + inter-cycle delays (< 1.0 = faster).
    Returns (send_mult, cycle_mult, reasons).
    """
    send_mult = 1.0
    cycle_mult = 1.0
    reasons: list[str] = []

    sr = cycle_success_rate if cycle_success_rate is not None else avg_success_rate
    if sr is not None:
        if sr >= 92:
            send_mult *= 0.82
            cycle_mult *= 0.78
            reasons.append("throughput_sr_excellent")
        elif sr >= SPEED_FAST_SUCCESS_RATE:
            send_mult *= 0.88
            cycle_mult *= 0.85
            reasons.append("throughput_sr_high")
        elif sr < 50:
            send_mult *= 1.18
            cycle_mult *= 1.15
            reasons.append("throughput_sr_low")

    if cycles_without_flood >= 3:
        send_mult *= 0.94
        cycle_mult *= 0.92
        reasons.append("throughput_flood_free")

    if flood_streak > 0:
        bump = 1.0 + 0.14 * min(flood_streak, 4)
        send_mult *= bump
        cycle_mult *= bump
        reasons.append("throughput_flood_streak")

    if health_score >= HEALTH_GOOD_THRESHOLD:
        send_mult *= 0.96
        cycle_mult *= 0.94
    elif health_score < HEALTH_MEDIUM_THRESHOLD:
        send_mult *= 1.12
        cycle_mult *= 1.08
        reasons.append("throughput_health_low")

    if last_cycle:
        end_reason = last_cycle.get("end_reason") or "complete"
        if end_reason in ("flood_break", "session_break"):
            send_mult *= 1.1
            cycle_mult *= 1.08
            reasons.append("throughput_last_cycle_interrupted")
        elif end_reason == "complete" and (last_cycle.get("success_rate") or 0) >= 85:
            cycle_mult *= 0.9
            reasons.append("throughput_last_cycle_clean")
        gps = float(last_cycle.get("groups_per_second") or 0)
        if gps >= 0.08 and end_reason == "complete":
            send_mult *= 0.95
            reasons.append("throughput_high_gps")

    send_mult = max(0.55, min(send_mult, 1.45))
    cycle_mult = max(0.55, min(cycle_mult, 1.45))
    return send_mult, cycle_mult, reasons


def compute_skip_delay(
    *,
    speed_mode: str = "normal",
    health_score: float = 100.0,
    skip_reason: str = "",
) -> int:
    """Short delay after skipped groups — faster than full send wait."""
    if skip_reason in ("recently_processed", "low_score_skip", "message_recent"):
        lo, hi = SKIP_DELAY_FAST_MIN_SECONDS, SKIP_DELAY_FAST_MAX_SECONDS
    elif speed_mode == "fast" and health_score >= HEALTH_GOOD_THRESHOLD:
        lo, hi = SKIP_DELAY_FAST_MIN_SECONDS, SKIP_DELAY_FAST_MAX_SECONDS
    else:
        lo, hi = SKIP_DELAY_MIN_SECONDS, SKIP_DELAY_MAX_SECONDS
    return max(1, random.randint(lo, hi))


def adaptive_join_budget(
    *,
    health_score: float,
    speed_mode: str,
    success_rate: float | None,
    fleet_pressure: float,
    heavy_rate_limit: bool,
    unhealthy: bool,
) -> tuple[int, int, bool]:
    """
    Returns (max_joins_per_cycle, min_groups_between_joins, proactive_join_enabled).
    """
    if heavy_rate_limit or unhealthy or fleet_pressure >= 0.5:
        return 0, 20, False

    if speed_mode == "fast" and health_score >= HEALTH_GOOD_THRESHOLD:
        max_joins = 3
        min_between = 6
        proactive = success_rate is None or success_rate >= 80
        return max_joins, min_between, proactive

    if health_score >= HEALTH_GOOD_THRESHOLD:
        max_joins = 2
        min_between = 8
        proactive = speed_mode == "fast"
        return max_joins, min_between, proactive

    if health_score >= HEALTH_MEDIUM_THRESHOLD:
        return 1, 12, False

    return 0, 20, False


def adaptive_post_join_delay(
    *,
    health_score: float,
    speed_mode: str = "normal",
    success_rate: float | None = None,
) -> float:
    """Shorter post-join wait for healthy / fast accounts."""
    if health_score >= HEALTH_GOOD_THRESHOLD:
        lo, hi = POST_JOIN_DELAY_GOOD_MIN, POST_JOIN_DELAY_GOOD_MAX
        if speed_mode == "fast":
            lo = max(8, int(lo * 0.65))
            hi = max(lo + 5, int(hi * 0.7))
        elif success_rate is not None and success_rate >= SPEED_FAST_SUCCESS_RATE:
            lo = max(10, int(lo * 0.8))
            hi = max(lo + 8, int(hi * 0.85))
    elif health_score >= HEALTH_MEDIUM_THRESHOLD:
        lo, hi = POST_JOIN_DELAY_MED_MIN, POST_JOIN_DELAY_MED_MAX
    else:
        lo, hi = POST_JOIN_DELAY_LOW_MIN, POST_JOIN_DELAY_LOW_MAX

    if speed_mode == "cautious":
        lo = int(lo * 1.15)
        hi = int(hi * 1.15)

    return random.uniform(lo, hi)


def tune_batch_profile(profile, *, health_score: float) -> None:
    """In-place health tuning for batch break size/duration."""
    if not hasattr(profile, "batch_groups_lo"):
        return
    if health_score >= HEALTH_GOOD_THRESHOLD:
        profile.batch_groups_lo = max(profile.batch_groups_lo, profile.batch_groups_lo + 2)
        profile.batch_groups_hi = min(35, profile.batch_groups_hi + 4)
        profile.batch_break_lo = max(40, int(profile.batch_break_lo * 0.92))
        profile.batch_break_hi = max(profile.batch_break_lo + 10, int(profile.batch_break_hi * 0.9))
    elif health_score < HEALTH_MEDIUM_THRESHOLD:
        profile.batch_groups_lo = max(6, profile.batch_groups_lo - 2)
        profile.batch_groups_hi = max(profile.batch_groups_lo + 2, profile.batch_groups_hi - 4)
        profile.batch_break_lo = int(profile.batch_break_lo * 1.1)
        profile.batch_break_hi = int(profile.batch_break_hi * 1.12)


def prioritize_groups_throughput(
    intel: GroupIntelligence,
    groups: list[str],
    *,
    speed_mode: str = "normal",
) -> list[str]:
    """
    High-score groups first; join candidates early; risky/recent last.
    Light randomness within tiers avoids fixed patterns.
    """
    if not groups:
        return []

    def rank(name: str) -> tuple:
        score = intel.get_score(name)
        risky = intel.is_risky(name)
        recent = intel.was_recently_processed(name)
        member = intel.get_membership_hint(name) == "member"
        join_rate = intel.get_join_success_rate(name)
        join_bad = intel.get_join_attempts(name) >= 2 and join_rate < 0.3

        if risky or join_bad:
            tier = 4
        elif recent:
            tier = 3
        elif not member and score >= PRE_JOIN_MIN_SCORE and speed_mode in ("fast", "normal"):
            tier = 0
        elif score >= 3:
            tier = 1
        elif member:
            tier = 1
        else:
            tier = 2

        return (tier, -score, random.random())

    return sorted(groups, key=rank)


def should_smart_pre_join(
    group: str,
    slot: str,
    intel: GroupIntelligence,
    ctx,
    *,
    score: int,
) -> bool:
    """Deterministic pre-join for top scorers in fast/healthy mode."""
    from core.unified_scheduler import _join_soft_allowed

    if not ctx.proactive_join_enabled:
        return False
    if ctx.joins_this_cycle >= ctx.max_joins_per_cycle:
        return False
    if ctx.groups_since_last_join < ctx.min_groups_between_joins:
        return False
    if intel.get_membership_hint(group) == "member":
        return False
    if score < PRE_JOIN_MIN_SCORE:
        return False

    ok, _ = _join_soft_allowed(group, slot, intel, ctx)
    if not ok:
        return False

    if ctx.speed_mode == "fast" and score >= 6:
        return True
    if score >= 8:
        return random.random() < 0.65
    return random.random() < 0.12
