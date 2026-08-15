"""Unified outbound dispatch — Telegram or WhatsApp."""

from __future__ import annotations

from typing import Any


async def dispatch_lead_reply(
    slot: str,
    user_id: int,
    text: str,
    *,
    sent_by: str = "manual",
    channel: str | None = None,
) -> dict[str, Any]:
    """Send a reply on Telegram or WhatsApp."""
    from core.whatsapp_channel import pick_reply_channel

    resolved = (channel or pick_reply_channel(slot, int(user_id))).strip().lower()
    if resolved == "whatsapp":
        from services import whatsapp_send_service

        result = await whatsapp_send_service.send_text(
            slot, int(user_id), text, sent_by=sent_by,
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "WhatsApp send failed")
        return {
            "message": result.get("message"),
            "conversation": result.get("conversation"),
            "channel": "whatsapp",
        }

    from services import dm_inbox_service

    send_res = await dm_inbox_service.run_dm_send(
        slot, int(user_id), text, sent_by=sent_by,
    )
    send_res["channel"] = "telegram"
    return send_res
