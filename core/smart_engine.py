"""
Smart sending intelligence — per-account group scoring, risky queue,
human-like delays, and account health. Persisted under data/accounts/{slot}/.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Any

from core.config import (
    BATCH_BREAK_GROUPS_MAX,
    BATCH_BREAK_GROUPS_MIN,
    BATCH_BREAK_MAX_SECONDS,
    BATCH_BREAK_MIN_SECONDS,
    CYCLE_DELAY_GOOD_MAX_SECONDS,
    CYCLE_DELAY_GOOD_MIN_SECONDS,
    CYCLE_DELAY_LOW_MAX_SECONDS,
    CYCLE_DELAY_LOW_MIN_SECONDS,
    CYCLE_DELAY_MAX_SECONDS,
    CYCLE_DELAY_MIN_SECONDS,
    ERROR_RECOVERY_MAX_SECONDS,
    ERROR_RECOVERY_MIN_SECONDS,
    FLOOD_MEDIUM_PAUSE_MAX_SECONDS,
    FLOOD_MEDIUM_PAUSE_MIN_SECONDS,
    FLOOD_SMALL_BUFFER_MAX,
    FLOOD_SMALL_BUFFER_MIN,
    GROUP_RECENT_COOLDOWN_SECONDS,
    GROUP_RETRY_MAX,
    HEALTH_GOOD_THRESHOLD,
    HEALTH_MEDIUM_THRESHOLD,
    RECENT_MESSAGE_LIMIT,
    RISKY_COOLDOWN_SECONDS,
    SEND_DELAY_GOOD_MAX_SECONDS,
    SEND_DELAY_GOOD_MIN_SECONDS,
    SEND_DELAY_JITTER_CHANCE,
    SEND_DELAY_JITTER_MAX,
    SEND_DELAY_JITTER_MIN,
    SEND_DELAY_LOW_MAX_SECONDS,
    SEND_DELAY_LOW_MIN_SECONDS,
    SEND_DELAY_MAX_SECONDS,
    SEND_DELAY_MIN_SECONDS,
    STILL_LIMITED_MAX_SECONDS,
    STILL_LIMITED_MIN_SECONDS,
    STATE_DIR,
)

INTEL_FILE = "group_intelligence.json"


def _intel_path(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, INTEL_FILE)


def _default_group_entry() -> dict:
    return {
        "success": 0,
        "failure": 0,
        "retries": 0,
        "score": 0,
        "last_processed": None,
        "risky_until": None,
        "last_result": "",
        "join_attempts": 0,
        "join_successes": 0,
        "last_membership": "unknown",
    }


def _default_account_meta() -> dict:
    return {
        "total_success": 0,
        "total_failure": 0,
        "rate_limits": 0,
        "health_score": 100.0,
        "delay_multiplier": 1.0,
        "cycles_without_flood": 0,
    }


class GroupIntelligence:
    """Per-account persistence for scoring, risky groups, and health."""

    def __init__(self, slot: str):
        self.slot = slot
        self._data: dict = {"groups": {}, "account": _default_account_meta()}
        self._load()

    def _load(self) -> None:
        path = _intel_path(self.slot)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._data["groups"] = raw.get("groups") or {}
                acct = raw.get("account") or {}
                base = _default_account_meta()
                base.update({k: acct[k] for k in base if k in acct})
                self._data["account"] = base
        except Exception:
            pass

    def save(self) -> None:
        path = _intel_path(self.slot)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception:
            pass

    def _group(self, name: str) -> dict:
        g = self._data["groups"].setdefault(name, _default_group_entry())
        return g

    @property
    def account_meta(self) -> dict:
        return self._data["account"]

    @property
    def health_score(self) -> float:
        return float(self.account_meta.get("health_score", 100.0))

    @property
    def delay_multiplier(self) -> float:
        return float(self.account_meta.get("delay_multiplier", 1.0))

    @property
    def cycles_without_flood(self) -> int:
        return int(self.account_meta.get("cycles_without_flood", 0))

    def record_cycle_flood_outcome(self, had_flood: bool) -> None:
        """Track clean cycles for flood-free speed boost."""
        if had_flood:
            self.account_meta["cycles_without_flood"] = 0
        else:
            self.account_meta["cycles_without_flood"] = self.cycles_without_flood + 1
        self.save()

    def is_risky(self, group: str) -> bool:
        g = self._group(group)
        until = g.get("risky_until")
        if not until:
            return False
        try:
            return time.time() < float(until)
        except (TypeError, ValueError):
            return False

    def was_recently_processed(self, group: str) -> bool:
        g = self._group(group)
        ts = g.get("last_processed")
        if not ts:
            return False
        try:
            return (time.time() - float(ts)) < GROUP_RECENT_COOLDOWN_SECONDS
        except (TypeError, ValueError):
            return False

    def get_score(self, group: str) -> int:
        return int(self._group(group).get("score", 0))

    def get_last_result(self, group: str) -> str:
        return str(self._group(group).get("last_result") or "")

    def get_join_attempts(self, group: str) -> int:
        return int(self._group(group).get("join_attempts", 0))

    def get_join_success_rate(self, group: str) -> float:
        g = self._group(group)
        attempts = int(g.get("join_attempts", 0))
        if attempts <= 0:
            return 1.0
        successes = int(g.get("join_successes", 0))
        return successes / attempts

    def get_membership_hint(self, group: str) -> str:
        return str(self._group(group).get("last_membership") or "unknown")

    def set_membership_hint(self, group: str, hint: str) -> None:
        g = self._group(group)
        g["last_membership"] = hint
        self.save()

    def record_join_outcome(self, group: str, outcome: str) -> None:
        """Track join attempts for UAS scoring."""
        g = self._group(group)
        g["join_attempts"] = int(g.get("join_attempts", 0)) + 1
        if outcome in ("joined_new", "already_in", "joined_sent", "pre_joined"):
            g["join_successes"] = int(g.get("join_successes", 0)) + 1
            g["last_membership"] = "member"
        elif outcome in ("blocked", "invalid", "cant_write"):
            g["last_membership"] = "not_member"
        self.save()

    def record_touch(self, group: str) -> None:
        g = self._group(group)
        g["last_processed"] = time.time()

    def record_result(self, group: str, result: str) -> None:
        """Update scores, retries, risky flag, and account health."""
        g = self._group(group)
        g["last_processed"] = time.time()
        g["last_result"] = result
        acct = self.account_meta

        success_codes = {"sent", "joined_sent", "ok", "skipped", "join_limited"}
        if result in ("sent", "joined_sent", "ok"):
            g["success"] = int(g.get("success", 0)) + 1
            g["retries"] = 0
            acct["total_success"] = int(acct.get("total_success", 0)) + 1
            self._bump_health(+1.5)
        elif result in ("skipped", "join_limited"):
            pass
        elif result == "pre_joined":
            pass
        elif result == "flood":
            g["failure"] = int(g.get("failure", 0)) + 1
            g["retries"] = int(g.get("retries", 0)) + 1
            acct["rate_limits"] = int(acct.get("rate_limits", 0)) + 1
            acct["total_failure"] = int(acct.get("total_failure", 0)) + 1
            self._bump_health(-8.0)
        elif result in ("invalid", "blocked", "cant_write"):
            g["failure"] = int(g.get("failure", 0)) + 1
            g["retries"] = int(g.get("retries", 0)) + 1
            acct["total_failure"] = int(acct.get("total_failure", 0)) + 1
            self._bump_health(-2.0)
        else:
            g["failure"] = int(g.get("failure", 0)) + 1
            g["retries"] = int(g.get("retries", 0)) + 1
            acct["total_failure"] = int(acct.get("total_failure", 0)) + 1
            self._bump_health(-3.0)

        g["score"] = int(g.get("success", 0)) - int(g.get("failure", 0))

        if int(g.get("retries", 0)) > GROUP_RETRY_MAX:
            g["risky_until"] = time.time() + RISKY_COOLDOWN_SECONDS

        self._sync_delay_multiplier()
        self.save()

    def _bump_health(self, delta: float) -> None:
        acct = self.account_meta
        score = max(0.0, min(100.0, float(acct.get("health_score", 100.0)) + delta))
        acct["health_score"] = round(score, 1)

    def _sync_delay_multiplier(self) -> None:
        from core.account_profile import get_delay_base_multiplier

        h = self.health_score
        if h >= HEALTH_GOOD_THRESHOLD:
            mult = 1.0
        elif h >= HEALTH_MEDIUM_THRESHOLD:
            mult = 1.12
        elif h >= 30:
            mult = 1.35
        else:
            mult = 1.6
        profile_floor = get_delay_base_multiplier(self.slot)
        self.account_meta["delay_multiplier"] = round(max(mult, profile_floor), 2)

    def health_tier(self) -> str:
        """good | medium | low — drives adaptive delay ranges."""
        h = self.health_score
        if h >= HEALTH_GOOD_THRESHOLD:
            return "good"
        if h >= HEALTH_MEDIUM_THRESHOLD:
            return "medium"
        return "low"

    def prioritize_groups(self, groups: list[str], *, speed_mode: str = "normal") -> list[str]:
        """High-score / join candidates first; risky and recent last."""
        from core.throughput_engine import prioritize_groups_throughput

        return prioritize_groups_throughput(self, groups, speed_mode=speed_mode)

    def precheck_skip_reason(
        self,
        group: str,
        *,
        account_sleeping: bool,
    ) -> str | None:
        if account_sleeping:
            return "account_sleeping"
        if self.is_risky(group):
            return "risky_group"
        if self.was_recently_processed(group):
            return "recently_processed"
        return None

    def next_batch_break_after(self, actions_since_break: int) -> int:
        """Random threshold between long breaks (default 12–18 groups)."""
        return random.randint(BATCH_BREAK_GROUPS_MIN, BATCH_BREAK_GROUPS_MAX)

    def compute_send_delay(
        self,
        *,
        flood_streak: int = 0,
        cycle_success_rate: float | None = None,
        speed: object | None = None,
    ) -> int:
        if speed is not None:
            from core.speed_optimizer import compute_send_delay as speed_send_delay

            return speed_send_delay(speed, flood_streak=flood_streak, policy_mult=1.0)
        tier = self.health_tier()
        if tier == "good":
            lo, hi = SEND_DELAY_GOOD_MIN_SECONDS, SEND_DELAY_GOOD_MAX_SECONDS
        elif tier == "low":
            lo, hi = SEND_DELAY_LOW_MIN_SECONDS, SEND_DELAY_LOW_MAX_SECONDS
        else:
            lo, hi = SEND_DELAY_MIN_SECONDS, SEND_DELAY_MAX_SECONDS
        base = random.randint(lo, hi)
        if random.random() < SEND_DELAY_JITTER_CHANCE:
            base += random.randint(SEND_DELAY_JITTER_MIN, SEND_DELAY_JITTER_MAX)
        mult = self.delay_multiplier if tier != "good" else 1.0
        if flood_streak > 0:
            mult *= 1.0 + 0.12 * min(flood_streak, 5)
        if cycle_success_rate is not None:
            if cycle_success_rate >= 90:
                mult *= 0.9
            elif cycle_success_rate >= 75:
                mult *= 0.95
            elif cycle_success_rate < 50:
                mult *= 1.2
            elif cycle_success_rate < 65:
                mult *= 1.1
        return max(SEND_DELAY_MIN_SECONDS, int(base * mult))

    def compute_cycle_delay(
        self, *, cycle_success_rate: float | None = None, speed: object | None = None
    ) -> int:
        if speed is not None:
            from core.speed_optimizer import compute_cycle_delay as speed_cycle_delay

            return speed_cycle_delay(speed, policy_mult=1.0)
        tier = self.health_tier()
        if tier == "good":
            lo, hi = CYCLE_DELAY_GOOD_MIN_SECONDS, CYCLE_DELAY_GOOD_MAX_SECONDS
            base = random.randint(lo, hi)
        elif tier == "low":
            lo, hi = CYCLE_DELAY_LOW_MIN_SECONDS, CYCLE_DELAY_LOW_MAX_SECONDS
            base = random.randint(lo, hi)
            base = max(lo, int(base * self.delay_multiplier))
        else:
            base = random.randint(CYCLE_DELAY_MIN_SECONDS, CYCLE_DELAY_MAX_SECONDS)
            base = max(CYCLE_DELAY_MIN_SECONDS, int(base * min(self.delay_multiplier, 1.15)))
        if cycle_success_rate is not None:
            if cycle_success_rate >= 85:
                base = int(base * 0.88)
            elif cycle_success_rate < 45:
                base = int(base * 1.15)
        return max(CYCLE_DELAY_MIN_SECONDS, base)

    def compute_batch_break_seconds(self, speed: object | None = None) -> int:
        if speed is not None:
            from core.speed_optimizer import compute_batch_break_seconds

            return compute_batch_break_seconds(speed)
        return random.randint(BATCH_BREAK_MIN_SECONDS, BATCH_BREAK_MAX_SECONDS)

    def small_flood_wait_seconds(self, telegram_secs: int) -> int:
        buffer = random.randint(FLOOD_SMALL_BUFFER_MIN, FLOOD_SMALL_BUFFER_MAX)
        return min(int(telegram_secs) + buffer, 120)

    def compute_medium_flood_pause(self, telegram_secs: int) -> int:
        """Medium flood: respect Telegram wait, target ~2–6 min randomized."""
        s = max(0, int(telegram_secs))
        target = random.randint(FLOOD_MEDIUM_PAUSE_MIN_SECONDS, FLOOD_MEDIUM_PAUSE_MAX_SECONDS)
        return max(s, target)

    def compute_still_limited_wait(self) -> int:
        return random.randint(STILL_LIMITED_MIN_SECONDS, STILL_LIMITED_MAX_SECONDS)

    def compute_error_recovery_wait(self) -> int:
        return random.randint(ERROR_RECOVERY_MIN_SECONDS, ERROR_RECOVERY_MAX_SECONDS)


def build_structured_log(
    *,
    account_id: str,
    group_id: str | None,
    action: str,
    reason: str,
    delay_used: int | None,
    level: str,
    message: str,
) -> dict[str, Any]:
    """Deprecated — use core.structured_logging.build_log_entry."""
    from core.structured_logging import build_structured_log as _build

    return _build(
        account_id=account_id,
        group_id=group_id,
        action=action,
        reason=reason,
        delay_used=delay_used,
        level=level,
        message=message,
    )


def recent_message_limit() -> int:
    return RECENT_MESSAGE_LIMIT
