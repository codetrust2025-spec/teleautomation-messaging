"""Outbound WhatsApp messages from dashboard / Karthik."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.config import ACCOUNTS, is_whatsapp_enabled
from core.contact_link_store import get_by_phone, get_by_telegram, link_phone
from core.dm_store import append_message, load_inbox
from core.phone_utils import normalize_phone
from core.whatsapp_templates import get_template
from services.whatsapp_bsp import get_bsp_client

logger = logging.getLogger(__name__)

_WA_WINDOW_SECONDS = 24 * 3600


def _extract_wa_message_id(response: dict | None) -> str:
    if not isinstance(response, dict):
        return ""
    for key in ("id", "message_id", "messageId"):
        if response.get(key):
            return str(response[key])
    message = response.get("message")
    if isinstance(message, dict):
        for key in ("id", "message_id"):
            if message.get(key):
                return str(message[key])
    data = response.get("data")
    if isinstance(data, dict):
        return _extract_wa_message_id(data)
    return ""


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def resolve_phone_for_lead(slot: str, user_id: int) -> str | None:
    link = get_by_telegram(slot, user_id)
    if link:
        return link["phone_e164"]
    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    phone = conv.get("phone_e164")
    if phone:
        return normalize_phone(str(phone))
    username = str(conv.get("username") or "")
    if username.startswith("wa:"):
        tail = username[3:].strip()
        norm = normalize_phone(tail) or normalize_phone(f"91{tail}")
        if norm:
            return norm
    for msg in reversed(conv.get("messages") or []):
        p = msg.get("phone_e164") or (msg.get("extra") or {}).get("phone_e164")
        if p:
            norm = normalize_phone(str(p))
            if norm:
                return norm
    from core.lead_graph import _mine_phone_from_history

    mined = _mine_phone_from_history(slot, user_id)
    return normalize_phone(mined) if mined else None


def _within_24h_window(slot: str, user_id: int) -> bool:
    from core.whatsapp_channel import last_inbound_channel

    if last_inbound_channel(slot, int(user_id)) != "whatsapp":
        return False
    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    last_in_ts = 0.0
    for msg in reversed(conv.get("messages") or []):
        if msg.get("direction") != "in":
            continue
        from core.whatsapp_channel import message_channel

        if message_channel(msg) != "whatsapp":
            continue
        ts = msg.get("timestamp")
        if not ts:
            continue
        try:
            last_in_ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
        break
    if not last_in_ts:
        return int(user_id) < 0
    return (_now_ts() - last_in_ts) <= _WA_WINDOW_SECONDS


async def send_text(
    slot: str,
    user_id: int,
    text: str,
    *,
    sent_by: str = "manual",
) -> dict[str, Any]:
    if not is_whatsapp_enabled():
        return {"ok": False, "error": "WhatsApp is disabled (WHATSAPP_ENABLED=0)"}
    if slot not in ACCOUNTS:
        return {"ok": False, "error": "Invalid slot"}

    phone = resolve_phone_for_lead(slot, user_id)
    if not phone:
        return {"ok": False, "error": "No phone linked for this lead"}

    if not _within_24h_window(slot, user_id):
        return {
            "ok": False,
            "error": "Outside 24h window — use send_template instead",
            "phone": phone,
        }

    client = get_bsp_client()
    if client is None or not client.configured:
        return {"ok": False, "error": "WhatsApp BSP not configured"}

    result = await client.send_text(phone, text)
    if not result.get("ok"):
        return result

    wa_mid = _extract_wa_message_id(result.get("response"))
    extra = {"channel": "whatsapp", "phone_e164": phone, "sent_by": sent_by}
    if wa_mid:
        extra["wa_message_id"] = wa_mid
    display_name = conv_name(slot, user_id) or phone
    conv, record, _ = append_message(
        slot,
        user_id=int(user_id),
        username=f"wa:{phone[-10:]}",
        name=display_name,
        text=text,
        direction="out",
        status="sent",
        increment_unread=False,
        account_id=slot,
        extra=extra,
    )
    link_phone(slot, int(user_id), phone, linked_by="send")

    from services.crm_service import enrich_conversation, touch_from_message

    touch_from_message(slot, int(user_id), direction="out")
    summary = enrich_conversation(
        slot,
        {
            "user_id": int(user_id),
            "username": conv.get("username"),
            "name": conv.get("name"),
            "last_message": conv.get("last_message"),
            "last_message_at": conv.get("last_message_at"),
            "unread_count": 0,
            "phone_e164": phone,
        },
    )

    from core import broadcast

    await broadcast.broadcast({
        "type": "inbox",
        "event": "reply_sent",
        "slot": slot,
        "conversation": summary,
        "message": record,
    })
    return {"ok": True, "message": record, "conversation": summary, "phone": phone}


async def send_template(
    slot: str,
    user_id: int,
    template_key: str,
    params: list[str],
    *,
    sent_by: str = "manual",
) -> dict[str, Any]:
    if not is_whatsapp_enabled():
        return {"ok": False, "error": "WhatsApp is disabled"}
    tpl = get_template(template_key)
    if not tpl:
        return {"ok": False, "error": f"Unknown template: {template_key}"}

    phone = resolve_phone_for_lead(slot, user_id)
    if not phone:
        return {"ok": False, "error": "No phone linked for this lead"}

    client = get_bsp_client()
    if client is None or not client.configured:
        return {"ok": False, "error": "WhatsApp BSP not configured"}

    bsp_name = str(tpl.get("bsp_name") or template_key)
    result = await client.send_template(phone, bsp_name, params)
    if not result.get("ok"):
        err = str(result.get("error") or "")
        resp = result.get("response")
        if not err and isinstance(resp, dict):
            err = str(resp.get("message") or "")
        err_l = err.lower()
        if "no approved template" in err_l or (
            "template" in err_l and ("approv" in err_l or "re-sync" in err_l)
        ):
            err = (
                "WhatsApp template is not approved yet. Create/sync "
                f"`{bsp_name}` in Interakt (Meta), wait for approval, then retry."
            )
        return {**result, "error": err or "Template send failed"}

    wa_mid = _extract_wa_message_id(result.get("response"))
    body = str(tpl.get("body") or template_key)
    for i, param in enumerate(params, start=1):
        body = body.replace(f"{{{{{i}}}}}", str(param))

    extra = {
        "channel": "whatsapp",
        "phone_e164": phone,
        "sent_by": sent_by,
        "template_name": bsp_name,
    }
    if wa_mid:
        extra["wa_message_id"] = wa_mid
    conv, record, _ = append_message(
        slot,
        user_id=int(user_id),
        username=f"wa:{phone[-10:]}",
        name=(conv_name(slot, user_id) or phone),
        text=body,
        direction="out",
        status="sent",
        increment_unread=False,
        account_id=slot,
        extra=extra,
    )
    link_phone(slot, int(user_id), phone, linked_by="send")
    return {"ok": True, "message": record, "phone": phone, "template": template_key}


def conv_name(slot: str, user_id: int) -> str:
    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    return str(conv.get("name") or "")


def status_snapshot() -> dict[str, Any]:
    client = get_bsp_client()
    return {
        "enabled": is_whatsapp_enabled(),
        "configured": bool(client and client.configured),
        "bsp": client.__class__.__name__ if client else None,
    }
