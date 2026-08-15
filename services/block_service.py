"""Block / unblock leads — CRM workflow + optional Telethon."""

from __future__ import annotations

import logging

from core.block_store import (
    BLOCK_REASON_SPAM,
    add_to_block_list,
    get_block_entry,
    is_blocked,
    list_blocked,
    remove_from_block_list,
)
from core.crm_store import upsert_lead

logger = logging.getLogger(__name__)


def _resolve_contact(slot: str, user_id: int) -> dict:
    from core.crm_store import get_lead
    from core.dm_store import list_conversations

    lead = get_lead(slot, user_id) or {}
    name = lead.get("name") or ""
    username = lead.get("username") or ""
    for c in list_conversations(slot):
        if int(c.get("user_id") or 0) == int(user_id):
            name = name or c.get("name") or ""
            username = username or c.get("username") or ""
            break
    return {"name": name, "username": username}


async def try_telegram_block(slot: str, user_id: int, *, block: bool) -> bool:
    """Best-effort Telethon block/unblock; returns True if API call succeeded."""
    try:
        from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
        from core import telegram_client

        client = await telegram_client.get_client(slot)
        entity = await client.get_input_entity(int(user_id))
        if block:
            await client(BlockRequest(id=entity))
        else:
            await client(UnblockRequest(id=entity))
        return True
    except Exception as e:
        logger.info("Telegram %s block %s:%s skipped: %s", "set" if block else "clear", slot, user_id, e)
        return False


async def block_lead(
    slot: str,
    user_id: int,
    *,
    reason: str = BLOCK_REASON_SPAM,
    telegram_block: bool = True,
) -> dict:
    """Add to block list, set CRM status spam, clear reminders/calls."""
    contact = _resolve_contact(slot, user_id)
    entry = add_to_block_list(
        slot,
        user_id,
        username=contact["username"],
        name=contact["name"],
        reason=reason,
    )
    try:
        from core.call_store import cancel_call

        cancel_call(slot, user_id)
    except Exception:
        pass

    lead = upsert_lead(
        slot,
        user_id,
        status="spam",
        name=contact["name"],
        username=contact["username"],
        reminder_timestamp=None,
    )

    if telegram_block:
        await try_telegram_block(slot, user_id, block=True)

    return {"entry": entry, "lead": lead}


async def unblock_lead(
    slot: str,
    user_id: int,
    *,
    telegram_unblock: bool = True,
) -> dict:
    """Remove from block list and restore lead to New."""
    remove_from_block_list(slot, user_id)
    contact = _resolve_contact(slot, user_id)
    lead = upsert_lead(
        slot,
        user_id,
        status="new",
        name=contact["name"],
        username=contact["username"],
        reminder_timestamp=None,
    )
    if telegram_unblock:
        await try_telegram_block(slot, user_id, block=False)
    return {"lead": lead}


def ensure_blocked_lead_status(slot: str, user_id: int, *, name: str = "", username: str = "") -> dict | None:
    """If user is on block list, ensure CRM status is spam (keeps history)."""
    if not is_blocked(slot, user_id):
        return None
    entry = get_block_entry(slot, user_id) or {}
    return upsert_lead(
        slot,
        user_id,
        status="spam",
        name=name or entry.get("name") or "",
        username=username or entry.get("username") or "",
    )


def assert_not_blocked(slot: str, user_id: int) -> None:
    if is_blocked(slot, user_id):
        raise ValueError("This lead is blocked. Open the Spam / Blocked tab to unblock first.")


def count_blocked() -> int:
    return len(list_blocked())


def list_blocked_payload() -> dict:
    return list_blocked()
