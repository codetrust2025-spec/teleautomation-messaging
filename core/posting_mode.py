"""Per-account posting mode: campaign cycles vs interval forwarding."""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass, field
from typing import Any

from core.account_features import (
    legacy_mode_label,
    migrate_enabled_flags,
    normalize_exclusive_flags,
)
from core.config import STATE_DIR

MODE_CAMPAIGN = "campaign"
MODE_FORWARDING = "forwarding"
MODES = frozenset({MODE_CAMPAIGN, MODE_FORWARDING, "both", "none"})

SOURCE_TEMPLATE = "template"
SOURCE_TELEGRAM = "telegram_post"
SOURCE_TYPES = frozenset({SOURCE_TEMPLATE, SOURCE_TELEGRAM})

FORWARD_DISPATCH_MANUAL = "manual"  # user selects groups + Send (one at a time)
FORWARD_DISPATCH_AUTO = "auto"  # legacy 24/7 random tick loop
FORWARD_DISPATCH_MODES = frozenset({FORWARD_DISPATCH_MANUAL, FORWARD_DISPATCH_AUTO})

FORWARD_INTERVAL_SECONDS = 20 * 60  # legacy default; ticks use random rest below
FORWARD_REST_MIN_SECONDS = int(os.environ.get("FORWARD_REST_MIN_SECONDS", str(10 * 60)))
FORWARD_REST_MAX_SECONDS = int(os.environ.get("FORWARD_REST_MAX_SECONDS", str(30 * 60)))


def pick_forward_rest_seconds() -> int:
    """Random gap before the next forward tick (default 10–30 minutes)."""
    lo = max(60, min(FORWARD_REST_MIN_SECONDS, FORWARD_REST_MAX_SECONDS))
    hi = max(lo, max(FORWARD_REST_MIN_SECONDS, FORWARD_REST_MAX_SECONDS))
    return random.randint(lo, hi)
# Within a tick: no per-group delay (burst all joined targets, then rest until next tick).
FORWARD_SPREAD_MIN_SECONDS = 0
FORWARD_SPREAD_MAX_SECONDS = 0
JOINED_TARGETS_CACHE_SECONDS = 6 * 3600

_TME_PUBLIC = re.compile(
    r"(?:https?://)?(?:www\.)?t\.me/([a-zA-Z0-9_]+)/(\d+)\s*$",
    re.I,
)
_TME_PRIVATE = re.compile(
    r"(?:https?://)?(?:www\.)?t\.me/c/(\d+)/(\d+)\s*$",
    re.I,
)


@dataclass
class ForwardingSettings:
    source_type: str = SOURCE_TEMPLATE
    source_peer: str = ""
    source_message_id: int = 0
    source_label: str = ""
    interval_seconds: int = FORWARD_INTERVAL_SECONDS
    spread_min_seconds: int = FORWARD_SPREAD_MIN_SECONDS
    spread_max_seconds: int = FORWARD_SPREAD_MAX_SECONDS
    include_channels: bool = True
    tick_group_offset: int = 0  # legacy; len(remaining pool) when using random tick pick
    tick_pending_keys: list[str] = field(default_factory=list)  # joined keys not used this round
    forward_dispatch: str = FORWARD_DISPATCH_AUTO
    forward_selected_target_ids: list[int] = field(default_factory=list)

    def is_configured(self, slot: str = "") -> bool:
        st = (self.source_type or SOURCE_TEMPLATE).strip().lower()
        if st == SOURCE_TELEGRAM:
            return bool(self.source_peer) and self.source_message_id > 0
        if not slot:
            return False
        from core.message_store import load_message_for_account

        return bool(load_message_for_account(slot).strip())

    def to_dict(self, slot: str = "") -> dict[str, Any]:
        st = (self.source_type or SOURCE_TEMPLATE).strip().lower()
        if st not in SOURCE_TYPES:
            st = SOURCE_TEMPLATE
        return {
            "source_type": st,
            "source_peer": self.source_peer,
            "source_message_id": self.source_message_id,
            "source_label": self.source_label,
            "interval_seconds": self.interval_seconds,
            "spread_min_seconds": self.spread_min_seconds,
            "spread_max_seconds": self.spread_max_seconds,
            "include_channels": self.include_channels,
            "tick_group_offset": int(self.tick_group_offset or 0),
            "tick_pending_keys": list(self.tick_pending_keys or []),
            "forward_dispatch": (
                self.forward_dispatch
                if self.forward_dispatch in FORWARD_DISPATCH_MODES
                else FORWARD_DISPATCH_AUTO
            ),
            "forward_selected_target_ids": [
                int(x) for x in (self.forward_selected_target_ids or []) if x is not None
            ],
            "configured": self.is_configured(slot),
        }


@dataclass
class PostingModeConfig:
    campaign_enabled: bool = True
    forwarding_enabled: bool = False
    forwarding: ForwardingSettings = field(default_factory=ForwardingSettings)
    mode: str = MODE_CAMPAIGN  # legacy; derived on save

    def to_dict(self, slot: str = "") -> dict[str, Any]:
        label = legacy_mode_label(self.campaign_enabled, self.forwarding_enabled)
        return {
            "campaign_enabled": self.campaign_enabled,
            "forwarding_enabled": self.forwarding_enabled,
            "mode": label,
            "forwarding": self.forwarding.to_dict(slot),
        }


def _config_path(slot: str) -> str:
    os.makedirs(os.path.join(STATE_DIR, slot), exist_ok=True)
    return os.path.join(STATE_DIR, slot, "posting_mode.json")


def _joined_cache_path(slot: str) -> str:
    os.makedirs(os.path.join(STATE_DIR, slot), exist_ok=True)
    return os.path.join(STATE_DIR, slot, "joined_forward_targets.json")


def parse_forward_source_url(url: str) -> tuple[str, int, str]:
    """
    Parse t.me post link → (source_peer, message_id, label).
    Supports public @channel/123 and private /c/id/123.
    """
    text = (url or "").strip()
    if not text:
        raise ValueError("Source URL is required")

    m = _TME_PRIVATE.match(text)
    if m:
        chan_id = int(m.group(1))
        msg_id = int(m.group(2))
        peer = f"-100{chan_id}"
        return peer, msg_id, f"c/{chan_id}/{msg_id}"

    m = _TME_PUBLIC.match(text)
    if m:
        username = m.group(1).lstrip("@")
        msg_id = int(m.group(2))
        return f"@{username}", msg_id, f"@{username}/{msg_id}"

    if "/" in text and text.count("/") >= 1:
        parts = text.rstrip("/").split("/")
        if parts[-1].isdigit():
            msg_id = int(parts[-1])
            peer_part = parts[-2].lstrip("@")
            if peer_part.isdigit():
                peer = f"-100{peer_part}"
                label = f"c/{peer_part}/{msg_id}"
            else:
                peer = f"@{peer_part}"
                label = f"@{peer_part}/{msg_id}"
            return peer, msg_id, label

    raise ValueError(
        "Use a Telegram post link, e.g. https://t.me/yourchannel/123"
    )


def load_posting_mode(slot: str) -> PostingModeConfig:
    path = _config_path(slot)
    if not os.path.exists(path):
        return PostingModeConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return PostingModeConfig()

    campaign_enabled, forwarding_enabled = migrate_enabled_flags(raw)

    fwd_raw = raw.get("forwarding") if isinstance(raw.get("forwarding"), dict) else {}
    source_type = str(fwd_raw.get("source_type") or "").strip().lower()
    if source_type not in SOURCE_TYPES:
        peer = str(fwd_raw.get("source_peer") or "").strip()
        msg_id = int(fwd_raw.get("source_message_id") or 0)
        source_type = SOURCE_TELEGRAM if peer and msg_id > 0 else SOURCE_TEMPLATE
    forwarding = ForwardingSettings(
        source_type=source_type,
        source_peer=str(fwd_raw.get("source_peer") or "").strip(),
        source_message_id=int(fwd_raw.get("source_message_id") or 0),
        source_label=str(fwd_raw.get("source_label") or "").strip(),
        interval_seconds=int(
            fwd_raw.get("interval_seconds") or FORWARD_INTERVAL_SECONDS
        ),
        spread_min_seconds=int(
            fwd_raw.get("spread_min_seconds") or FORWARD_SPREAD_MIN_SECONDS
        ),
        spread_max_seconds=int(
            fwd_raw.get("spread_max_seconds") or FORWARD_SPREAD_MAX_SECONDS
        ),
        include_channels=bool(fwd_raw.get("include_channels", True)),
        tick_group_offset=int(fwd_raw.get("tick_group_offset") or 0),
        tick_pending_keys=[
            str(k)
            for k in (fwd_raw.get("tick_pending_keys") or [])
            if k is not None and str(k).strip()
        ],
        forward_dispatch=(
            str(fwd_raw.get("forward_dispatch") or FORWARD_DISPATCH_AUTO).strip().lower()
            if str(fwd_raw.get("forward_dispatch") or FORWARD_DISPATCH_AUTO).strip().lower()
            in FORWARD_DISPATCH_MODES
            else FORWARD_DISPATCH_AUTO
        ),
        forward_selected_target_ids=[
            int(x)
            for x in (fwd_raw.get("forward_selected_target_ids") or [])
            if x is not None
        ],
    )
    if forwarding.interval_seconds < 300:
        forwarding.interval_seconds = FORWARD_INTERVAL_SECONDS
    # Legacy configs used 8–20s between each group; forwarding is burst-then-rest now.
    if forwarding.spread_min_seconds >= 8 or forwarding.spread_max_seconds >= 8:
        forwarding.spread_min_seconds = FORWARD_SPREAD_MIN_SECONDS
        forwarding.spread_max_seconds = FORWARD_SPREAD_MAX_SECONDS

    campaign_enabled, forwarding_enabled = normalize_exclusive_flags(
        campaign_enabled, forwarding_enabled
    )
    cfg = PostingModeConfig(
        campaign_enabled=campaign_enabled,
        forwarding_enabled=forwarding_enabled,
        forwarding=forwarding,
        mode=legacy_mode_label(campaign_enabled, forwarding_enabled),
    )
    legacy_both = (
        str(raw.get("mode") or "").strip().lower() == "both"
        or (
            "campaign_enabled" in raw
            and "forwarding_enabled" in raw
            and bool(raw.get("campaign_enabled"))
            and bool(raw.get("forwarding_enabled"))
        )
    )
    if legacy_both:
        save_posting_mode(slot, cfg)
    return cfg


def save_posting_mode(slot: str, config: PostingModeConfig) -> None:
    path = _config_path(slot)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(slot), f, indent=2)
    os.replace(tmp, path)


def save_forward_selection(slot: str, target_ids: list) -> PostingModeConfig:
    """Persist user-selected groups for manual forward cycle."""
    from core.telegram_forward import parse_target_ids

    cfg = load_posting_mode(slot)
    cfg.forwarding.forward_selected_target_ids = parse_target_ids(target_ids)
    save_posting_mode(slot, cfg)
    return cfg


def is_auto_forward_dispatch(slot: str) -> bool:
    cfg = load_posting_mode(slot)
    return (cfg.forwarding.forward_dispatch or FORWARD_DISPATCH_AUTO) == FORWARD_DISPATCH_AUTO


def set_feature_enabled(
    slot: str,
    *,
    campaign_enabled: bool | None = None,
    forwarding_enabled: bool | None = None,
) -> PostingModeConfig:
    cfg = load_posting_mode(slot)
    if campaign_enabled is not None:
        cfg.campaign_enabled = bool(campaign_enabled)
        if cfg.campaign_enabled:
            cfg.forwarding_enabled = False
    if forwarding_enabled is not None:
        cfg.forwarding_enabled = bool(forwarding_enabled)
        if cfg.forwarding_enabled:
            cfg.campaign_enabled = False
    cfg.campaign_enabled, cfg.forwarding_enabled = normalize_exclusive_flags(
        cfg.campaign_enabled, cfg.forwarding_enabled
    )
    cfg.mode = legacy_mode_label(cfg.campaign_enabled, cfg.forwarding_enabled)
    save_posting_mode(slot, cfg)
    return cfg


def set_posting_mode(
    slot: str,
    mode: str = "",
    *,
    forward_source_type: str | None = None,
    forward_dispatch: str | None = None,
    campaign_enabled: bool | None = None,
    forwarding_enabled: bool | None = None,
) -> PostingModeConfig:
    cfg = load_posting_mode(slot)
    mode_text = (mode or "").strip().lower()
    if mode_text:
        if mode_text not in MODES:
            raise ValueError(f"mode must be one of: {', '.join(sorted(MODES))}")
        if mode_text == MODE_FORWARDING:
            # Legacy single-mode: forwarding-only (periodic join every 2 forward ticks).
            cfg.campaign_enabled = False
            cfg.forwarding_enabled = True
        elif mode_text == MODE_CAMPAIGN:
            # Legacy single-mode: campaign scheduler joins only (no forward-tick joins).
            cfg.campaign_enabled = True
            cfg.forwarding_enabled = False
        elif mode_text == "both":
            cfg.campaign_enabled = False
            cfg.forwarding_enabled = True
        elif mode_text == "none":
            cfg.campaign_enabled = False
            cfg.forwarding_enabled = False
        cfg.mode = legacy_mode_label(cfg.campaign_enabled, cfg.forwarding_enabled)
    elif (
        forward_source_type is None
        and forward_dispatch is None
        and campaign_enabled is None
        and forwarding_enabled is None
    ):
        raise ValueError(
            "mode, campaign_enabled, forwarding_enabled, forward_source_type, or forward_dispatch required"
        )
    if campaign_enabled is not None:
        cfg.campaign_enabled = bool(campaign_enabled)
        if cfg.campaign_enabled:
            cfg.forwarding_enabled = False
    if forwarding_enabled is not None:
        cfg.forwarding_enabled = bool(forwarding_enabled)
        if cfg.forwarding_enabled:
            cfg.campaign_enabled = False
    cfg.campaign_enabled, cfg.forwarding_enabled = normalize_exclusive_flags(
        cfg.campaign_enabled, cfg.forwarding_enabled
    )
    if forward_source_type is not None:
        st = (forward_source_type or SOURCE_TEMPLATE).strip().lower()
        if st not in SOURCE_TYPES:
            raise ValueError(
                f"forward source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}"
            )
        cfg.forwarding.source_type = st
        if st == SOURCE_TEMPLATE:
            cfg.forwarding.source_peer = ""
            cfg.forwarding.source_message_id = 0
            cfg.forwarding.source_label = ""
    if forward_dispatch is not None:
        fd = str(forward_dispatch).strip().lower()
        if fd not in FORWARD_DISPATCH_MODES:
            raise ValueError(
                f"forward_dispatch must be one of: {', '.join(sorted(FORWARD_DISPATCH_MODES))}"
            )
        cfg.forwarding.forward_dispatch = fd
    cfg.mode = legacy_mode_label(cfg.campaign_enabled, cfg.forwarding_enabled)
    save_posting_mode(slot, cfg)
    return cfg


def set_forwarding_source(
    slot: str,
    *,
    source_url: str | None = None,
    source_peer: str | None = None,
    source_message_id: int | None = None,
) -> PostingModeConfig:
    cfg = load_posting_mode(slot)
    if source_url:
        peer, msg_id, label = parse_forward_source_url(source_url)
    elif source_peer and source_message_id:
        peer = source_peer.strip()
        if peer and not peer.startswith("@") and not peer.startswith("-") and peer.lstrip("-").isdigit():
            peer = f"-100{peer.lstrip('-')}"
        msg_id = int(source_message_id)
        label = f"{peer}/{msg_id}"
    else:
        raise ValueError("source_url or source_peer + source_message_id required")

    cfg.forwarding.source_type = SOURCE_TELEGRAM
    cfg.forwarding.source_peer = peer
    cfg.forwarding.source_message_id = msg_id
    cfg.forwarding.source_label = label
    save_posting_mode(slot, cfg)
    return cfg


def set_forwarding_source_type(slot: str, source_type: str) -> PostingModeConfig:
    st = (source_type or SOURCE_TEMPLATE).strip().lower()
    if st not in SOURCE_TYPES:
        raise ValueError(
            f"source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}"
        )
    cfg = load_posting_mode(slot)
    cfg.forwarding.source_type = st
    if st == SOURCE_TEMPLATE:
        cfg.forwarding.source_peer = ""
        cfg.forwarding.source_message_id = 0
        cfg.forwarding.source_label = ""
    save_posting_mode(slot, cfg)
    return cfg


def load_joined_targets_cache(slot: str) -> list[dict] | None:
    path = _joined_cache_path(slot)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        import time

        updated = float(data.get("updated_at") or 0)
        if time.time() - updated > JOINED_TARGETS_CACHE_SECONDS:
            return None
        targets = data.get("targets")
        return list(targets) if isinstance(targets, list) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def save_joined_targets_cache(slot: str, targets: list[dict]) -> None:
    import time

    path = _joined_cache_path(slot)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            {"updated_at": time.time(), "targets": targets},
            f,
            indent=2,
        )
    os.replace(tmp, path)


def clear_joined_targets_cache(slot: str) -> None:
    """Force next forward tick to rescan joined dialogs (e.g. after a new join)."""
    path = _joined_cache_path(slot)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def all_posting_modes() -> dict[str, dict[str, Any]]:
    from core.config import ACCOUNT_SLOTS

    return {
        slot: load_posting_mode(slot).to_dict(slot) for slot in ACCOUNT_SLOTS
    }
