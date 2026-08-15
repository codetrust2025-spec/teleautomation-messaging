"""Detect Telegram voice/video calls and notify the CRM dashboard."""

from __future__ import annotations

import logging
from typing import Any

from telethon import TelegramClient
from telethon.tl.types import (
    PhoneCallDiscarded,
    PhoneCallRequested,
    UpdatePhoneCall,
    User,
)

from core import broadcast

logger = logging.getLogger(__name__)

_ringing: dict[str, int] = {}


async def _peer_meta(client: TelegramClient, user_id: int) -> dict[str, Any]:
    try:
        ent = await client.get_entity(int(user_id))
    except Exception:
        return {"user_id": int(user_id), "name": str(user_id), "username": ""}
    if not isinstance(ent, User):
        return {"user_id": int(user_id), "name": str(user_id), "username": ""}
    username = (getattr(ent, "username", None) or "").strip()
    first = (getattr(ent, "first_name", None) or "").strip()
    last = (getattr(ent, "last_name", None) or "").strip()
    name = " ".join(p for p in (first, last) if p).strip() or username or str(user_id)
    return {"user_id": int(user_id), "name": name, "username": username}


async def handle_phone_call_update(
    slot: str,
    client: TelegramClient,
    update: UpdatePhoneCall,
) -> None:
    call = update.phone_call
    if isinstance(call, PhoneCallRequested):
        caller_id = int(getattr(call, "participant_id", 0) or 0)
        if caller_id <= 0:
            return
        meta = await _peer_meta(client, caller_id)
        call_id = int(call.id)
        _ringing[slot] = call_id
        payload = {
            "type": "incoming_call",
            "event": "ringing",
            "slot": slot,
            "call": {
                "call_id": call_id,
                "access_hash": int(getattr(call, "access_hash", 0) or 0),
                "user_id": meta["user_id"],
                "name": meta["name"],
                "username": meta["username"],
                "video": bool(getattr(call, "video", False)),
            },
        }
        logger.info(
            "Incoming Telegram call on %s from %s (%s)",
            slot,
            meta["name"],
            caller_id,
        )
        await broadcast.broadcast(payload)
        return

    if isinstance(call, PhoneCallDiscarded):
        call_id = int(call.id)
        if _ringing.get(slot) == call_id:
            _ringing.pop(slot, None)
        await broadcast.broadcast({
            "type": "incoming_call",
            "event": "ended",
            "slot": slot,
            "call": {"call_id": call_id},
        })


def make_phone_call_handler(slot: str, client: TelegramClient):
    async def handler(event) -> None:
        try:
            update = event
            if not isinstance(update, UpdatePhoneCall):
                update = getattr(event, "update", None)
            if isinstance(update, UpdatePhoneCall):
                await handle_phone_call_update(slot, client, update)
        except Exception as e:
            logger.warning("phone call handler %s: %s", slot, e)

    return handler
