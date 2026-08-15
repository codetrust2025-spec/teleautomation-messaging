"""Mutable state for ONE account only — never shared between accounts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Set


@dataclass
class AccountState:
    slot: str
    running: bool = False  # supervisor active (any feature may run)
    task: object | None = None  # asyncio.Task
    logs: list = field(default_factory=list)
    my_groups: list = field(default_factory=list)
    notification: str = ""
    invalid_groups: Set[str] = field(default_factory=set)
    blocked_groups: Set[str] = field(default_factory=set)
    account_info: dict | None = None
    flood_streak: int = 0
    heavy_rate_limit: bool = False
    health_score: float = 100.0
    delay_multiplier: float = 1.0
    cycle_message_preview: str = ""
    last_activity_at: float = 0.0
    worker_started_at: float = 0.0
    cycle_metrics: dict | None = None
    execution_policy: dict | None = None
    speed_profile: dict | None = None
    forward_source_label: str = ""
    posting_mode: str = "campaign"  # legacy label: campaign | forwarding | both | none
    status: str = "stopped"  # aggregate UI/lifecycle status (mirrors active feature)

    # --- Campaign runtime (independent) ---
    campaign_running: bool = False
    campaign_status: str = "stopped"
    campaign_cycle: int = 0
    campaign_success: int = 0
    campaign_failed: int = 0
    campaign_skipped_already_posted: int = 0
    campaign_skipped_cooldown: int = 0
    campaign_skipped_other: int = 0
    campaign_current_group: str = ""
    campaign_success_list: list = field(default_factory=list)
    campaign_failed_list: list = field(default_factory=list)
    campaign_active_groups: int = 0
    campaign_next_cycle_in: int = 0

    # --- Forwarding runtime (independent) ---
    forwarding_running: bool = False
    forwarding_status: str = "stopped"
    forwarding_cycle: int = 0
    forwarding_success: int = 0
    forwarding_failed: int = 0
    forwarding_skipped_already_posted: int = 0
    forwarding_failed_list: list = field(default_factory=list)
    forwarding_failure_counts: dict = field(default_factory=dict)
    forwarding_current_group: str = ""
    forwarding_active_groups: int = 0
    forwarding_next_cycle_in: int = 0
    forwarding_batch: int = 0
    forwarding_batch_total: int = 0
    forwarding_batch_size: int = 0
    forwarding_joined_total: int = 0

    def _feature_dict(self, prefix: str, *, extra: dict | None = None) -> dict[str, Any]:
        base = {
            "running": bool(getattr(self, f"{prefix}_running")),
            "status": getattr(self, f"{prefix}_status", "stopped"),
            "cycle": int(getattr(self, f"{prefix}_cycle", 0) or 0),
            "success": int(getattr(self, f"{prefix}_success", 0) or 0),
            "failed": int(getattr(self, f"{prefix}_failed", 0) or 0),
            "skipped_already_posted": int(
                getattr(self, f"{prefix}_skipped_already_posted", 0) or 0
            ),
            "current_group": getattr(self, f"{prefix}_current_group", "") or "",
            "active_groups": int(getattr(self, f"{prefix}_active_groups", 0) or 0),
            "next_cycle_in": int(getattr(self, f"{prefix}_next_cycle_in", 0) or 0),
        }
        if prefix == "campaign":
            base["skipped_cooldown"] = self.campaign_skipped_cooldown
            base["skipped_other"] = self.campaign_skipped_other
            base["success_list"] = list(self.campaign_success_list)
            base["failed_list"] = list(self.campaign_failed_list)
        if prefix == "forwarding":
            base["forward_batch"] = self.forwarding_batch
            base["forward_batch_total"] = self.forwarding_batch_total
            base["forward_batch_size"] = self.forwarding_batch_size
            base["forward_joined_total"] = self.forwarding_joined_total
            base["failed_list"] = list(self.forwarding_failed_list)[-40:]
            base["failure_counts"] = dict(self.forwarding_failure_counts)
        if extra:
            base.update(extra)
        return base

    def _legacy_primary_prefix(self) -> str:
        if self.campaign_running:
            return "campaign"
        if self.forwarding_running:
            return "forwarding"
        mode = (self.posting_mode or "campaign").strip().lower()
        if mode in ("forwarding", "both"):
            return "forwarding"
        return "campaign"

    def to_dict(self) -> dict:
        try:
            from core.send_stats import count_24h, count_24h_for_mode

            messages_sent_24h = count_24h(self.slot)
            forward_posts_24h = count_24h(self.slot, "forward")
            campaign_posts_24h = count_24h(self.slot, "campaign")
        except Exception:
            messages_sent_24h = 0
            forward_posts_24h = 0
            campaign_posts_24h = 0

        primary = self._legacy_primary_prefix()
        p_cycle = getattr(self, f"{primary}_cycle", 0)
        p_success = getattr(self, f"{primary}_success", 0)
        p_failed = getattr(self, f"{primary}_failed", 0)
        p_skip = getattr(self, f"{primary}_skipped_already_posted", 0)
        p_current = getattr(self, f"{primary}_current_group", "")
        p_active = getattr(self, f"{primary}_active_groups", 0)
        p_next = getattr(self, f"{primary}_next_cycle_in", 0)
        p_status = getattr(self, f"{primary}_status", "stopped")

        any_running = self.campaign_running or self.forwarding_running

        return {
            "running": any_running,
            "campaign": self._feature_dict("campaign"),
            "forwarding": self._feature_dict("forwarding"),
            "cycle": p_cycle,
            "success": p_success,
            "failed": p_failed,
            "skipped_already_posted": p_skip,
            "skipped_cooldown": self.campaign_skipped_cooldown,
            "skipped_other": self.campaign_skipped_other,
            "skipped_total": (
                p_skip + self.campaign_skipped_cooldown + self.campaign_skipped_other
            ),
            "messages_sent_24h": messages_sent_24h,
            "forward_posts_24h": forward_posts_24h,
            "campaign_posts_24h": campaign_posts_24h,
            "current_group": p_current,
            "success_list": list(self.campaign_success_list),
            "failed_list": list(self.campaign_failed_list),
            "logs": list(self.logs[-100:]),
            "active_groups": p_active,
            "status": (
                self.status
                if any_running and self.status not in ("", "stopped")
                else (p_status if any_running else "stopped")
            ),
            "my_groups": list(self.my_groups),
            "next_cycle_in": max(self.campaign_next_cycle_in, self.forwarding_next_cycle_in),
            "notification": self.notification,
            "heavy_rate_limit": self.heavy_rate_limit,
            "health_score": self.health_score,
            "delay_multiplier": self.delay_multiplier,
            "cycle_message_preview": self.cycle_message_preview,
            "cycle_metrics": dict(self.cycle_metrics) if self.cycle_metrics else None,
            "execution_policy": dict(self.execution_policy) if self.execution_policy else None,
            "speed_profile": dict(self.speed_profile) if self.speed_profile else None,
            "posting_mode": self.posting_mode,
            "forward_source_label": self.forward_source_label,
            "forward_batch": self.forwarding_batch,
            "forward_batch_total": self.forwarding_batch_total,
            "forward_batch_size": self.forwarding_batch_size,
            "forward_joined_total": self.forwarding_joined_total,
            "campaign_running": self.campaign_running,
            "forwarding_running": self.forwarding_running,
        }

    def should_continue(self) -> bool:
        return self.running

    def should_continue_campaign(self) -> bool:
        return self.running and self.campaign_running

    def should_continue_forwarding(self) -> bool:
        return self.running and self.forwarding_running
