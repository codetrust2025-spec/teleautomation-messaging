"""Independent campaign vs forwarding feature flags and runtime helpers."""

from __future__ import annotations

from typing import Any

MODE_CAMPAIGN = "campaign"
MODE_FORWARDING = "forwarding"


def normalize_exclusive_flags(
    campaign_enabled: bool, forwarding_enabled: bool
) -> tuple[bool, bool]:
    """At most one feature on; if both were set, keep forwarding."""
    if campaign_enabled and forwarding_enabled:
        return False, True
    return campaign_enabled, forwarding_enabled


def legacy_mode_label(campaign_enabled: bool, forwarding_enabled: bool) -> str:
    """Backward-compatible single mode string for old clients."""
    campaign_enabled, forwarding_enabled = normalize_exclusive_flags(
        campaign_enabled, forwarding_enabled
    )
    if forwarding_enabled:
        return MODE_FORWARDING
    if campaign_enabled:
        return MODE_CAMPAIGN
    return "none"


def migrate_enabled_flags(raw: dict[str, Any]) -> tuple[bool, bool]:
    """Load campaign_enabled / forwarding_enabled with legacy mode migration."""
    if "campaign_enabled" in raw or "forwarding_enabled" in raw:
        campaign = bool(raw.get("campaign_enabled", True))
        forwarding = bool(raw.get("forwarding_enabled", False))
        return normalize_exclusive_flags(campaign, forwarding)
    mode = str(raw.get("mode") or MODE_CAMPAIGN).strip().lower()
    if mode == MODE_FORWARDING:
        return False, True
    if mode == "both":
        return False, True
    if mode == "none":
        return False, False
    return True, False
