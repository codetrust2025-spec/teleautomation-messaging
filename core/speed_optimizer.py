"""
Safe speed optimization — up to ~2× throughput for healthy accounts without raising ban risk.

Fast mode requires multiple safety signals (health, success rate, flood-free streak, low fleet pressure).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core.config import (
    BATCH_BREAK_FAST_MAX_SECONDS,
    BATCH_BREAK_FAST_MIN_SECONDS,
    BATCH_BREAK_GROUPS_FAST_MAX,
    BATCH_BREAK_GROUPS_FAST_MIN,
    BATCH_BREAK_GROUPS_MAX,
    BATCH_BREAK_GROUPS_MIN,
    BATCH_BREAK_GROUPS_SAFE_MAX,
    BATCH_BREAK_GROUPS_SAFE_MIN,
    BATCH_BREAK_MAX_SECONDS,
    BATCH_BREAK_MIN_SECONDS,
    BATCH_BREAK_SAFE_MAX_SECONDS,
    BATCH_BREAK_SAFE_MIN_SECONDS,
    CYCLE_DELAY_FAST_MAX_SECONDS,
    CYCLE_DELAY_FAST_MIN_SECONDS,
    CYCLE_DELAY_GOOD_MAX_SECONDS,
    CYCLE_DELAY_GOOD_MIN_SECONDS,
    CYCLE_DELAY_LOW_MAX_SECONDS,
    CYCLE_DELAY_LOW_MIN_SECONDS,
    CYCLE_DELAY_MAX_SECONDS,
    CYCLE_DELAY_MIN_SECONDS,
    DELAY_JITTER_PCT,
    FLOOD_FREE_BOOST_MAX,
    FLOOD_FREE_BOOST_STEP,
    HEALTH_GOOD_THRESHOLD,
    SEND_DELAY_FAST_MAX_SECONDS,
    SEND_DELAY_FAST_MIN_SECONDS,
    SEND_DELAY_GOOD_MAX_SECONDS,
    SEND_DELAY_GOOD_MIN_SECONDS,
    SEND_DELAY_LOW_MAX_SECONDS,
    SEND_DELAY_LOW_MIN_SECONDS,
    SEND_DELAY_MAX_SECONDS,
    SEND_DELAY_MIN_SECONDS,
    SPEED_FAST_MIN_CLEAN_CYCLES,
    SPEED_FAST_SUCCESS_RATE,
)


@dataclass
class SpeedProfile:
    """Per-cycle speed tuning — attached to worker for one cycle duration."""

    mode: str  # fast | normal | cautious
    send_lo: int
    send_hi: int
    cycle_lo: int
    cycle_hi: int
    batch_groups_lo: int
    batch_groups_hi: int
    batch_break_lo: int
    batch_break_hi: int
    compression: float = 1.0
    cycle_scale: float = 1.0
    flood_free_boost: float = 1.0
    jitter_pct: float = DELAY_JITTER_PCT
    reasons: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "send_range": [self.send_lo, self.send_hi],
            "cycle_range": [self.cycle_lo, self.cycle_hi],
            "batch_groups_range": [self.batch_groups_lo, self.batch_groups_hi],
            "batch_break_range": [self.batch_break_lo, self.batch_break_hi],
            "compression": round(self.compression, 3),
            "cycle_scale": round(self.cycle_scale, 3),
            "flood_free_boost": round(self.flood_free_boost, 3),
            "jitter_pct": self.jitter_pct,
            "reasons": list(self.reasons or []),
        }


def apply_jitter(seconds: int, pct: float = DELAY_JITTER_PCT) -> int:
    """±pct randomness — breaks timing patterns (default ±15%)."""
    if seconds <= 0:
        return 0
    factor = 1.0 + random.uniform(-pct, pct)
    return max(1, int(round(seconds * factor)))


def flood_free_boost(cycles_without_flood: int) -> float:
    """Gradually speed up when no floods — capped boost."""
    if cycles_without_flood <= 0:
        return 1.0
    boost = 1.0 - FLOOD_FREE_BOOST_STEP * min(cycles_without_flood, 5)
    return max(FLOOD_FREE_BOOST_MAX, boost)


def _is_fast_eligible(
    *,
    health_score: float,
    cycle_success_rate: float | None,
    avg_success_rate: float | None,
    flood_streak: int,
    cycles_without_flood: int,
    fleet_pressure: float,
    unhealthy: bool,
    heavy_rate_limit: bool,
    recently_flooded: bool,
) -> bool:
    if unhealthy or heavy_rate_limit or recently_flooded:
        return False
    if flood_streak > 0 or fleet_pressure >= 0.25:
        return False
    if health_score < HEALTH_GOOD_THRESHOLD:
        return False
    sr = cycle_success_rate if cycle_success_rate is not None else avg_success_rate
    if sr is None or sr < SPEED_FAST_SUCCESS_RATE:
        return False
    if cycles_without_flood < SPEED_FAST_MIN_CLEAN_CYCLES:
        return False
    return True


def _is_cautious(
    *,
    health_score: float,
    flood_streak: int,
    fleet_pressure: float,
    unhealthy: bool,
    avg_success_rate: float | None,
) -> bool:
    if unhealthy or flood_streak >= 2 or fleet_pressure >= 0.5:
        return True
    if health_score < 50:
        return True
    if avg_success_rate is not None and avg_success_rate < 50:
        return True
    return False


def compute_speed_profile(
    *,
    health_score: float,
    health_tier: str,
    cycle_success_rate: float | None,
    avg_success_rate: float | None,
    flood_streak: int,
    cycles_without_flood: int,
    fleet_pressure: float,
    unhealthy: bool,
    heavy_rate_limit: bool,
    recently_flooded: bool,
    last_cycle: dict | None = None,
) -> SpeedProfile:
    from core.throughput_engine import throughput_multipliers, tune_batch_profile

    reasons: list[str] = []
    ff_boost = flood_free_boost(cycles_without_flood)

    if _is_cautious(
        health_score=health_score,
        flood_streak=flood_streak,
        fleet_pressure=fleet_pressure,
        unhealthy=unhealthy,
        avg_success_rate=avg_success_rate,
    ):
        reasons.append("cautious_signals")
        return SpeedProfile(
            mode="cautious",
            send_lo=SEND_DELAY_LOW_MIN_SECONDS,
            send_hi=SEND_DELAY_LOW_MAX_SECONDS,
            cycle_lo=CYCLE_DELAY_LOW_MIN_SECONDS,
            cycle_hi=CYCLE_DELAY_LOW_MAX_SECONDS,
            batch_groups_lo=BATCH_BREAK_GROUPS_SAFE_MIN,
            batch_groups_hi=BATCH_BREAK_GROUPS_SAFE_MAX,
            batch_break_lo=BATCH_BREAK_SAFE_MIN_SECONDS,
            batch_break_hi=BATCH_BREAK_SAFE_MAX_SECONDS,
            compression=1.15,
            flood_free_boost=1.0,
            reasons=reasons,
        )

    if _is_fast_eligible(
        health_score=health_score,
        cycle_success_rate=cycle_success_rate,
        avg_success_rate=avg_success_rate,
        flood_streak=flood_streak,
        cycles_without_flood=cycles_without_flood,
        fleet_pressure=fleet_pressure,
        unhealthy=unhealthy,
        heavy_rate_limit=heavy_rate_limit,
        recently_flooded=recently_flooded,
    ):
        reasons.extend(["fast_mode", f"flood_free_{cycles_without_flood}"])
        if cycle_success_rate and cycle_success_rate >= SPEED_FAST_SUCCESS_RATE:
            reasons.append("high_success_rate")
        tp_send, tp_cycle, tp_reasons = throughput_multipliers(
            health_score=health_score,
            cycle_success_rate=cycle_success_rate,
            avg_success_rate=avg_success_rate,
            flood_streak=flood_streak,
            cycles_without_flood=cycles_without_flood,
            last_cycle=last_cycle,
        )
        reasons.extend(tp_reasons)
        profile = SpeedProfile(
            mode="fast",
            send_lo=SEND_DELAY_FAST_MIN_SECONDS,
            send_hi=SEND_DELAY_FAST_MAX_SECONDS,
            cycle_lo=CYCLE_DELAY_FAST_MIN_SECONDS,
            cycle_hi=CYCLE_DELAY_FAST_MAX_SECONDS,
            batch_groups_lo=BATCH_BREAK_GROUPS_FAST_MIN,
            batch_groups_hi=BATCH_BREAK_GROUPS_FAST_MAX,
            batch_break_lo=BATCH_BREAK_FAST_MIN_SECONDS,
            batch_break_hi=BATCH_BREAK_FAST_MAX_SECONDS,
            compression=0.92 * tp_send,
            cycle_scale=tp_cycle,
            flood_free_boost=ff_boost,
            reasons=reasons,
        )
        tune_batch_profile(profile, health_score=health_score)
        return profile

    # Normal — tier-based with mild compression when healthy
    if health_tier == "good":
        send_lo, send_hi = SEND_DELAY_GOOD_MIN_SECONDS, SEND_DELAY_GOOD_MAX_SECONDS
        cycle_lo, cycle_hi = CYCLE_DELAY_GOOD_MIN_SECONDS, CYCLE_DELAY_GOOD_MAX_SECONDS
        compression = 0.95 if (avg_success_rate or 0) >= 75 else 1.0
    elif health_tier == "low":
        send_lo, send_hi = SEND_DELAY_LOW_MIN_SECONDS, SEND_DELAY_LOW_MAX_SECONDS
        cycle_lo, cycle_hi = CYCLE_DELAY_LOW_MIN_SECONDS, CYCLE_DELAY_LOW_MAX_SECONDS
        compression = 1.1
    else:
        send_lo, send_hi = SEND_DELAY_MIN_SECONDS, SEND_DELAY_MAX_SECONDS
        cycle_lo, cycle_hi = CYCLE_DELAY_MIN_SECONDS, CYCLE_DELAY_MAX_SECONDS
        compression = 1.0

    sr = cycle_success_rate if cycle_success_rate is not None else avg_success_rate
    if sr is not None and sr >= SPEED_FAST_SUCCESS_RATE:
        cycle_lo, cycle_hi = CYCLE_DELAY_FAST_MIN_SECONDS, CYCLE_DELAY_FAST_MAX_SECONDS
        reasons.append("fast_inter_cycle")

    tp_send, tp_cycle, tp_reasons = throughput_multipliers(
        health_score=health_score,
        cycle_success_rate=cycle_success_rate,
        avg_success_rate=avg_success_rate,
        flood_streak=flood_streak,
        cycles_without_flood=cycles_without_flood,
        last_cycle=last_cycle,
    )
    reasons.extend(tp_reasons)

    profile = SpeedProfile(
        mode="normal",
        send_lo=send_lo,
        send_hi=send_hi,
        cycle_lo=cycle_lo,
        cycle_hi=cycle_hi,
        batch_groups_lo=BATCH_BREAK_GROUPS_MIN,
        batch_groups_hi=BATCH_BREAK_GROUPS_MAX,
        batch_break_lo=BATCH_BREAK_MIN_SECONDS,
        batch_break_hi=BATCH_BREAK_MAX_SECONDS,
        compression=compression * tp_send,
        cycle_scale=tp_cycle,
        flood_free_boost=ff_boost if cycles_without_flood >= 1 else 1.0,
        reasons=reasons or ["normal"],
    )
    tune_batch_profile(profile, health_score=health_score)
    profile.compression = max(0.55, min(profile.compression, 1.35))
    return profile


def compute_send_delay(profile: SpeedProfile, *, flood_streak: int = 0, policy_mult: float = 1.0) -> int:
    base = random.randint(profile.send_lo, profile.send_hi)
    mult = profile.compression * profile.flood_free_boost * policy_mult
    if flood_streak > 0:
        mult *= 1.0 + 0.12 * min(flood_streak, 5)
    return apply_jitter(max(SEND_DELAY_MIN_SECONDS, int(base * mult)), profile.jitter_pct)


def compute_cycle_delay(profile: SpeedProfile, *, policy_mult: float = 1.0) -> int:
    from core.config import CYCLE_DELAY_MIN_SECONDS

    base = random.randint(profile.cycle_lo, profile.cycle_hi)
    mult = (
        profile.compression
        * profile.cycle_scale
        * profile.flood_free_boost
        * policy_mult
    )
    return apply_jitter(max(CYCLE_DELAY_MIN_SECONDS, int(base * mult)), profile.jitter_pct)


def next_batch_break_after(profile: SpeedProfile) -> int:
    return random.randint(profile.batch_groups_lo, profile.batch_groups_hi)


def compute_batch_break_seconds(profile: SpeedProfile) -> int:
    base = random.randint(profile.batch_break_lo, profile.batch_break_hi)
    return apply_jitter(base, profile.jitter_pct)


async def wait_with_parallel_prep(
    seconds: int,
    should_continue: Callable[[], bool],
    prep: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Sleep while optionally running async prep (next delay, precheck) in parallel."""
    import asyncio

    from features.delay_handler import wait_seconds

    if seconds <= 0:
        if prep:
            await prep()
        return
    if prep and seconds >= 2:
        prep_task = asyncio.create_task(prep())
        await wait_seconds(seconds, should_continue)
        if not prep_task.done():
            try:
                await prep_task
            except Exception:
                pass
        return
    await wait_seconds(seconds, should_continue)
