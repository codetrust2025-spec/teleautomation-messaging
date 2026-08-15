"""Handle inbound WhatsApp webhooks — append to unified inbox."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core import broadcast
from core.config import ACCOUNTS, WHATSAPP_DEFAULT_SLOT, is_whatsapp_enabled
from core.contact_link_store import get_by_phone, link_phone
from core.dm_store import append_message, load_inbox
from core.phone_utils import normalize_phone
from core.whatsapp_identity import phone_to_synthetic_user_id, wa_message_id_to_int
from services.whatsapp_bsp import InboundWaMessage, WaStatusUpdate

logger = logging.getLogger(__name__)


async def _cache_inbound_media(
    slot: str,
    user_id: int,
    message_id: int,
    wa_media_id: str,
    mime: str | None,
) -> None:
    """Background: download WA image, patch message, optionally attach candidate proof."""
    from core.dm_store import patch_message
    from services.whatsapp_media_service import (
        ensure_message_media_cached,
        maybe_save_payment_proof_from_wa,
    )

    try:
        cached = await ensure_message_media_cached(slot, user_id, message_id, wa_media_id)
        if not cached:
            return
        updated = patch_message(
            slot,
            user_id,
            message_id,
            {
                "wa_media_url": cached["url"],
                "wa_media_cached": True,
                "media": "image",
            },
        )
        if updated and cached.get("path"):
            with open(cached["path"], "rb") as f:
                data = f.read()
            maybe_save_payment_proof_from_wa(
                slot, user_id, data, str(cached.get("mime") or mime or "image/jpeg"),
            )
        if updated:
            from services.crm_service import enrich_conversation

            conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
            summary = enrich_conversation(slot, _conversation_summary({**conv, "user_id": user_id}))
            await _broadcast_inbox(slot, "message_updated", conversation=summary, message=updated)
    except Exception as exc:
        logger.warning("WA media cache %s %s: %s", slot, user_id, exc)


def _default_slot() -> str:
    if WHATSAPP_DEFAULT_SLOT in ACCOUNTS:
        return WHATSAPP_DEFAULT_SLOT
    return next(iter(ACCOUNTS), "account1")


def _resolve_lead(msg: InboundWaMessage) -> tuple[str, int, bool]:
    """Return (slot, user_id, is_synthetic_wa_only)."""
    link = get_by_phone(msg.from_phone_e164)
    if link:
        return link["account_slot"], int(link["telegram_user_id"]), False
    slot = _default_slot()
    uid = phone_to_synthetic_user_id(msg.from_phone_e164)
    return slot, uid, True


async def _broadcast_inbox(
    slot: str,
    event: str,
    *,
    conversation: dict | None = None,
    message: dict | None = None,
) -> None:
    payload: dict[str, Any] = {
        "type": "inbox",
        "event": event,
        "slot": slot,
    }
    if conversation is not None:
        payload["conversation"] = conversation
    if message is not None:
        payload["message"] = message
    await broadcast.broadcast(payload)


def _conversation_summary(conv: dict) -> dict:
    return {
        "user_id": conv["user_id"],
        "username": conv.get("username"),
        "name": conv.get("name"),
        "last_message": conv.get("last_message"),
        "last_message_at": conv.get("last_message_at"),
        "unread_count": conv.get("unread_count"),
        "phone_e164": conv.get("phone_e164"),
        "channels": conv.get("channels") or ["whatsapp"],
    }


async def handle_inbound_message(msg: InboundWaMessage) -> dict:
    """Persist inbound WhatsApp message and notify dashboard."""
    if not is_whatsapp_enabled():
        return {"ok": False, "reason": "whatsapp_disabled"}

    phone = normalize_phone(msg.from_phone_e164)
    if not phone:
        return {"ok": False, "reason": "invalid_phone"}

    slot, user_id, wa_only = _resolve_lead(msg)
    if slot not in ACCOUNTS:
        return {"ok": False, "reason": "invalid_slot"}

    if not wa_only:
        link_phone(slot, user_id, phone, linked_by="auto", profile_name=msg.profile_name)
    else:
        # WA-only thread — store phone on synthetic lead for operators.
        from core.crm_store import upsert_lead

        upsert_lead(
            slot,
            user_id,
            name=msg.profile_name or phone,
            notes=f"WhatsApp-only lead ({phone})",
        )

    display_name = (msg.profile_name or "").strip() or phone
    username = f"wa:{phone[-10:]}"
    msg_id = wa_message_id_to_int(msg.wa_message_id) if msg.wa_message_id else None

    extra: dict[str, Any] = {
        "channel": "whatsapp",
        "wa_message_id": msg.wa_message_id,
        "phone_e164": phone,
    }
    if msg.media_url:
        extra["wa_media_id"] = msg.media_url
        extra["wa_media_mime"] = msg.media_mime

    media = None
    if msg.message_type in ("image", "sticker"):
        media = "image"
    elif msg.message_type in ("document", "video", "audio"):
        media = msg.message_type

    conv, record, created = append_message(
        slot,
        user_id=user_id,
        username=username,
        name=display_name,
        text=msg.text,
        direction="in",
        telegram_id=msg_id,
        status="received",
        increment_unread=True,
        account_id=slot,
        media=media,
        extra=extra,
    )
    if not created:
        return {"ok": True, "duplicate": True, "slot": slot, "user_id": user_id}

    conv["phone_e164"] = phone
    conv["channels"] = sorted(set((conv.get("channels") or []) + ["whatsapp"]))

    from services.crm_service import enrich_conversation, touch_from_message
    from services.block_service import ensure_blocked_lead_status

    touch_from_message(
        slot,
        user_id,
        direction="in",
        name=display_name,
        username=username,
    )
    ensure_blocked_lead_status(slot, user_id, name=display_name, username=username)
    summary = enrich_conversation(slot, _conversation_summary(conv))

    await _broadcast_inbox(slot, "new_message", conversation=summary, message=record)

    if msg.message_type in ("image", "document", "video", "audio", "sticker") and msg.media_url:
        import asyncio

        asyncio.create_task(
            _cache_inbound_media(slot, user_id, int(record.get("id") or 0), msg.media_url, msg.media_mime)
        )

    try:
        from core import ai_smart_reply
        from services.crm_service import get_lead

        await ai_smart_reply.maybe_schedule_ai_reply(
            slot,
            user_id,
            message_id=record.get("id"),
            text=msg.text,
            lead=get_lead(slot, user_id),
        )
    except Exception as exc:
        logger.warning("whatsapp ai trigger %s %s: %s", slot, user_id, exc)

    logger.info("WhatsApp inbound %s %s from %s", slot, user_id, phone)
    return {"ok": True, "slot": slot, "user_id": user_id, "phone": phone, "wa_only": wa_only}


async def handle_status_update(st: WaStatusUpdate) -> dict:
    """Advance outbound message delivery status when BSP sends callbacks."""
    if not st.wa_message_id or not st.status:
        return {"ok": False, "reason": "empty_status"}

    from core.dm_store import find_message_by_wa_id_any_slot, update_outbound_status

    hit = find_message_by_wa_id_any_slot(st.wa_message_id)
    if not hit:
        logger.debug("WhatsApp status %s — message not found locally", st.wa_message_id)
        return {"ok": True, "matched": False}

    slot, user_id, msg = hit
    status_map = {
        "sent": "sent",
        "delivered": "delivered",
        "read": "read",
        "failed": "failed",
    }
    mapped = status_map.get(str(st.status).lower())
    if not mapped:
        return {"ok": True, "ignored": st.status}

    updated = update_outbound_status(slot, user_id, int(msg.get("id") or 0), mapped)
    if updated:
        from services.crm_service import enrich_conversation

        conv = (load_inbox(slot).get("conversations") or {}).get(str(user_id)) or {}
        summary = enrich_conversation(slot, _conversation_summary({**conv, "user_id": user_id}))
        await _broadcast_inbox(
            slot,
            "status",
            conversation=summary,
            message=updated,
        )
    return {"ok": True, "matched": True, "status": mapped, "slot": slot, "user_id": user_id}


async def process_webhook_payload(payload: dict) -> dict:
    from services.whatsapp_bsp import parse_webhook_payload

    inbound, statuses = parse_webhook_payload(payload)
    results: dict[str, Any] = {"inbound": [], "statuses": []}
    for msg in inbound:
        results["inbound"].append(await handle_inbound_message(msg))
    for st in statuses:
        results["statuses"].append(await handle_status_update(st))
    return results
