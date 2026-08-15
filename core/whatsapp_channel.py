"""Reply channel selection — Telegram vs WhatsApp."""

from __future__ import annotations

from core.config import is_whatsapp_enabled


def message_channel(message: dict) -> str:
    ch = (message.get("channel") or "").strip().lower()
    if ch in ("whatsapp", "telegram"):
        return ch
    return "telegram"


def last_inbound_channel(slot: str, user_id: int) -> str:
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    for msg in reversed(conv.get("messages") or []):
        if msg.get("direction") == "in":
            return message_channel(msg)
    return "telegram"


def pick_reply_channel(slot: str, user_id: int) -> str:
    """Choose outbound channel: WhatsApp when enabled and lead is on WA thread."""
    if not is_whatsapp_enabled():
        return "telegram"
    uid = int(user_id)
    if uid < 0:
        return "whatsapp"
    from services.whatsapp_send_service import resolve_phone_for_lead

    if not resolve_phone_for_lead(slot, uid):
        return "telegram"
    if last_inbound_channel(slot, uid) == "whatsapp":
        return "whatsapp"
    return "telegram"


def conversation_channels(slot: str, user_id: int) -> list[str]:
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    found: set[str] = set()
    for msg in conv.get("messages") or []:
        if msg.get("direction") in ("in", "out"):
            found.add(message_channel(msg))
    if int(user_id) < 0:
        found.add("whatsapp")
    if not found:
        found.add("telegram")
    return sorted(found)
