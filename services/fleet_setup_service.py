"""Bulk apply forwarding/campaign setup across logged-in accounts."""

from __future__ import annotations

from typing import Any

from core.account_info_store import load_account_info
from core.config import ACCOUNTS, ACCOUNT_SLOTS
from core.fleet_defaults import get_fleet_defaults, save_fleet_defaults
from core.message_store import save_message_for_account
from core.posting_mode import set_forwarding_source, set_posting_mode


def _logged_in_slots() -> list[str]:
    out: list[str] = []
    for slot in ACCOUNT_SLOTS:
        row = load_account_info(slot)
        if row and (row.get("phone") or row.get("user_id")):
            out.append(slot)
    return out


def apply_forwarding_bulk(
    slots: list[str] | None = None,
    *,
    source_url: str | None = None,
    use_saved_default: bool = False,
    forward_dispatch: str = "auto",
    registry=None,
) -> dict[str, Any]:
    url = (source_url or "").strip()
    if use_saved_default and not url:
        url = get_fleet_defaults().get("forward_source_url") or ""
    targets = slots if slots else _logged_in_slots()
    updated: list[str] = []
    skipped_running: list[str] = []
    errors: dict[str, str] = {}

    for slot in targets:
        if slot not in ACCOUNTS:
            continue
        w = registry.get_worker(slot) if registry else None
        if w and w.state.running:
            skipped_running.append(slot)
            continue
        try:
            set_posting_mode(
                slot,
                "forwarding",
                forward_dispatch=forward_dispatch,
                campaign_enabled=False,
                forwarding_enabled=True,
            )
            if url:
                set_forwarding_source(slot, source_url=url)
            if w:
                w._sync_posting_mode_ui()
            updated.append(slot)
        except Exception as e:
            errors[slot] = str(e)[:200]

    return {
        "updated": updated,
        "skipped_running": skipped_running,
        "errors": errors,
        "source_url": url or None,
    }


def apply_campaign_bulk(
    slots: list[str] | None = None,
    *,
    message: str | None = None,
    use_saved_default: bool = False,
    registry=None,
) -> dict[str, Any]:
    text = (message or "").strip()
    if use_saved_default and not text:
        text = get_fleet_defaults().get("campaign_message") or ""
    targets = slots if slots else _logged_in_slots()
    updated: list[str] = []
    skipped_running: list[str] = []
    errors: dict[str, str] = {}

    for slot in targets:
        if slot not in ACCOUNTS:
            continue
        w = registry.get_worker(slot) if registry else None
        if w and w.state.running:
            skipped_running.append(slot)
            continue
        try:
            set_posting_mode(
                slot,
                "campaign",
                campaign_enabled=True,
                forwarding_enabled=False,
            )
            if text:
                save_message_for_account(slot, text)
            if w:
                w._sync_posting_mode_ui()
            updated.append(slot)
        except Exception as e:
            errors[slot] = str(e)[:200]

    return {
        "updated": updated,
        "skipped_running": skipped_running,
        "errors": errors,
        "message_chars": len(text) if text else 0,
    }


def apply_forward_source_only(
    slots: list[str] | None = None,
    *,
    source_url: str | None = None,
    use_saved_default: bool = False,
    registry=None,
) -> dict[str, Any]:
    """Set t.me source on accounts that already have forwarding enabled."""
    url = (source_url or "").strip()
    if use_saved_default and not url:
        url = get_fleet_defaults().get("forward_source_url") or ""
    if not url:
        raise ValueError("source_url or saved default required")
    from core.posting_mode import load_posting_mode

    targets = slots if slots else _logged_in_slots()
    updated: list[str] = []
    skipped_running: list[str] = []
    skipped_mode: list[str] = []
    errors: dict[str, str] = {}

    for slot in targets:
        if slot not in ACCOUNTS:
            continue
        cfg = load_posting_mode(slot)
        if not cfg.forwarding_enabled:
            skipped_mode.append(slot)
            continue
        w = registry.get_worker(slot) if registry else None
        if w and w.state.running:
            skipped_running.append(slot)
            continue
        try:
            set_forwarding_source(slot, source_url=url)
            if w:
                w._sync_posting_mode_ui()
            updated.append(slot)
        except Exception as e:
            errors[slot] = str(e)[:200]

    return {
        "updated": updated,
        "skipped_running": skipped_running,
        "skipped_mode": skipped_mode,
        "errors": errors,
        "source_url": url,
    }


def save_defaults_and_apply(
    *,
    workspace: str,
    forward_source_url: str | None = None,
    campaign_message: str | None = None,
    registry=None,
) -> dict[str, Any]:
    """Save fleet defaults then apply to all logged-in accounts for that workspace."""
    if forward_source_url is not None or campaign_message is not None:
        save_fleet_defaults(
            forward_source_url=forward_source_url,
            campaign_message=campaign_message,
        )
    ws = (workspace or "").strip().lower()
    if ws in ("forwarding", "forward"):
        return apply_forwarding_bulk(
            use_saved_default=True,
            source_url=forward_source_url,
            registry=registry,
        )
    if ws == "campaign":
        return apply_campaign_bulk(
            use_saved_default=True,
            message=campaign_message,
            registry=registry,
        )
    raise ValueError("workspace must be forwarding or campaign")
