"""
Independent DM inbox — private chats only.
Hooks Telethon NewMessage on any connected client; no imports from account_worker.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from telethon import TelegramClient, events
from telethon.tl.types import User

from core import broadcast, telegram_client
from core.account_info_store import load_account_info
from core.config import ACCOUNTS
from core.dm_filter import validate_incoming_dm, validate_outgoing_dm
from core.dm_store import (
    append_message,
    build_slot_payload as _dm_build_slot_payload,
    load_inbox,
    mark_all_outgoing_read,
    mark_conversation_read,
    mark_outbound_delivered,
    mark_outgoing_read_up_to,
)

logger = logging.getLogger(__name__)

_handlers_attached: set[str] = set()
_handler_refs: dict[str, dict[str, Any]] = {}
_handler_clients: dict[str, TelegramClient] = {}
_listener_clients: dict[str, TelegramClient] = {}
_listener_refresh_tasks: dict[str, asyncio.Task] = {}
_bootstrap_done = False


def _is_logged_in(slot: str) -> bool:
    info = load_account_info(slot)
    return bool(info and info.get("phone"))


async def _broadcast_status(
    slot: str,
    user_id: int,
    message: dict,
    *,
    conversation: dict | None = None,
) -> None:
    """Real-time outbound status change (sent → delivered → read)."""
    await _broadcast_inbox(
        slot,
        "message_status",
        conversation=conversation or {"user_id": user_id},
        message={
            "user_id": user_id,
            "chat_id": message.get("chat_id", user_id),
            "account_id": slot,
            "message_id": message.get("id"),
            "status": message.get("status"),
            "read_at": message.get("read_at"),
            "direction": message.get("direction"),
            "text": message.get("text"),
            "timestamp": message.get("timestamp"),
        },
    )


async def _broadcast_inbox(
    slot: str,
    event: str,
    *,
    conversation: dict | None = None,
    message: dict | None = None,
) -> None:
    payload: dict = {
        "type": "inbox",
        "event": event,
        "slot": slot,
        "inbox": build_slot_payload(slot),
    }
    if conversation is not None:
        payload["conversation"] = conversation
    if message is not None:
        payload["message"] = message
    await broadcast.broadcast(payload)


async def _broadcast_daily_stats() -> None:
    """Push recalculated daily counters after inbox activity."""
    import asyncio

    from core.daily_stats import compute_daily_stats

    daily_stats = await asyncio.to_thread(compute_daily_stats, list(ACCOUNTS))
    await broadcast.broadcast({
        "type": "daily_stats",
        "daily_stats": daily_stats,
    })


def build_slot_payload(slot: str) -> dict:
    from services.crm_service import enrich_conversation

    raw = _dm_build_slot_payload(slot)
    raw["conversations"] = [
        enrich_conversation(slot, c) for c in raw.get("conversations") or []
    ]
    return raw


def _conversation_summary(conv: dict) -> dict:
    return {
        "user_id": conv["user_id"],
        "username": conv.get("username"),
        "name": conv.get("name"),
        "last_message": conv.get("last_message"),
        "last_message_at": conv.get("last_message_at"),
        "unread_count": conv.get("unread_count"),
    }


async def _handle_dm_event(
    slot: str,
    event: events.NewMessage.Event,
    *,
    direction: str,
    increment_unread: bool,
) -> None:
    if direction == "in":
        ok, meta = await validate_incoming_dm(event)
    else:
        ok, meta = await validate_outgoing_dm(event)
    if not ok or not meta:
        return

    from core.dm_media import message_media_meta

    media_meta = message_media_meta(event.message)
    text = (event.message.message or "").strip()
    if not text and not media_meta:
        return
    if not text and media_meta:
        text = media_meta["placeholder"]

    status = "received" if direction == "in" else "sent"
    conv, record, created = append_message(
        slot,
        user_id=meta["user_id"],
        username=meta["username"],
        name=meta["name"],
        text=text,
        direction=direction,
        telegram_id=event.message.id,
        status=status,
        increment_unread=increment_unread,
        account_id=slot,
        media=bool(media_meta),
        media_type=media_meta.get("media_type") if media_meta else None,
    )
    if not created:
        return

    from services.crm_service import enrich_conversation, touch_from_message

    touch_from_message(
        slot,
        meta["user_id"],
        direction=direction,
        name=meta.get("name") or "",
        username=meta.get("username") or "",
    )
    from services.block_service import ensure_blocked_lead_status

    ensure_blocked_lead_status(
        slot,
        meta["user_id"],
        name=meta.get("name") or "",
        username=meta.get("username") or "",
    )
    summary = enrich_conversation(slot, _conversation_summary(conv))
    uid = meta["user_id"]

    if direction == "in":
        try:
            from services.spam_guard_service import maybe_auto_block_inbound

            block_hit = await maybe_auto_block_inbound(
                slot,
                uid,
                text,
                name=meta.get("name") or "",
                username=meta.get("username") or "",
            )
            if block_hit:
                summary = enrich_conversation(slot, _conversation_summary(conv))
                await _broadcast_inbox(
                    slot,
                    "lead_blocked",
                    conversation=summary,
                    message=record,
                )
                await _broadcast_daily_stats()
                return
        except Exception as e:
            logger.debug("spam guard %s:%s: %s", slot, uid, e)
        read_updates = mark_all_outgoing_read(slot, uid)
        try:
            from events.event_bus import event_bus
            from events.event_types import EventType

            await event_bus.publish(
                EventType.MESSAGE_RECEIVED,
                slot,
                {
                    "user_id": uid,
                    "username": meta.get("username", ""),
                    "name": meta.get("name", ""),
                    "message_id": record.get("id"),
                },
                push_state=False,
            )
        except Exception:
            pass
        await _broadcast_inbox(
            slot,
            "new_message",
            conversation=summary,
            message=record,
        )
        for m in read_updates:
            await _broadcast_status(slot, uid, m, conversation=summary)
        await _broadcast_daily_stats()

        try:
            from features import web_push

            asyncio.create_task(
                web_push.notify_new_inbound_message(
                    slot=slot,
                    user_id=int(uid),
                    name=meta.get("name"),
                    username=meta.get("username"),
                    text=text or "",
                ),
                name=f"web_push_{slot}_{uid}",
            )
        except Exception as e:
            logger.debug("web_push notify %s:%s: %s", slot, uid, e)

        try:
            from core import ai_smart_reply
            from core.crm_store import get_lead

            asyncio.create_task(
                ai_smart_reply.maybe_schedule_ai_reply(
                    slot,
                    int(uid),
                    message_id=record.get("id"),
                    text=text or "",
                    lead=get_lead(slot, int(uid)),
                ),
                name=f"karthik_schedule_{slot}_{uid}",
            )
        except Exception as e:
            logger.debug("karthik schedule %s:%s: %s", slot, uid, e)
        return

    await _broadcast_inbox(
        slot,
        "outgoing_message",
        conversation=summary,
        message=record,
    )
    delivered = mark_outbound_delivered(slot, uid, record["id"])
    if delivered:
        await _broadcast_status(slot, uid, delivered, conversation=summary)
    await _broadcast_daily_stats()


async def _on_incoming_message(slot: str, event: events.NewMessage.Event) -> None:
    try:
        await _handle_dm_event(slot, event, direction="in", increment_unread=True)
    except Exception as e:
        logger.warning("DM inbox incoming %s: %s", slot, e)


async def _on_outgoing_message(slot: str, event: events.NewMessage.Event) -> None:
    try:
        await _handle_dm_event(slot, event, direction="out", increment_unread=False)
    except Exception as e:
        logger.warning("DM inbox outgoing %s: %s", slot, e)


async def _resolve_private_user_id(event: events.MessageRead.Event) -> int | None:
    if not getattr(event, "is_private", False):
        return None
    try:
        chat = await event.get_chat()
    except Exception:
        return None
    from core.dm_filter import is_private_dm_chat

    if not is_private_dm_chat(chat):
        return None
    return int(chat.id)


async def _on_message_read_outbox(slot: str, event: events.MessageRead.Event) -> None:
    """Recipient read our outbound messages (Telegram double-check)."""
    try:
        user_id = await _resolve_private_user_id(event)
        if user_id is None:
            return

        max_id = int(getattr(event, "max_id", 0) or 0)
        if not max_id and getattr(event, "message_ids", None):
            max_id = max(int(x) for x in event.message_ids)

        if max_id <= 0:
            return

        updated = mark_outgoing_read_up_to(slot, user_id, max_id)
        if not updated:
            return

        data = load_inbox(slot)
        conv = data.get("conversations", {}).get(str(user_id), {})
        summary = _conversation_summary(conv) if conv else {"user_id": user_id}
        await _broadcast_inbox(
            slot,
            "message_read",
            conversation=summary,
            message={"user_id": user_id, "max_id": max_id, "updated": len(updated)},
        )
        for m in updated:
            await _broadcast_status(slot, user_id, m, conversation=summary)
    except Exception as e:
        logger.warning("DM inbox read receipt %s: %s", slot, e)


async def _fetch_read_outbox_max_id(client: TelegramClient, user_id: int) -> int:
    """Telegram's read_outbox_max_id for a private chat."""
    try:
        entity = await client.get_entity(int(user_id))
        target = int(entity.id)
        async for dialog in client.iter_dialogs(limit=80):
            ent = dialog.entity
            if getattr(ent, "id", None) == target:
                return int(dialog.dialog.read_outbox_max_id or 0)
    except Exception as e:
        logger.debug("read_outbox_max_id %s: %s", user_id, e)
    return 0


async def sync_read_receipts(slot: str, user_id: int) -> list[dict]:
    """Apply Telegram read state to stored messages before returning to UI."""
    from core.dm_store import load_inbox, save_inbox, infer_outgoing_read_from_thread

    async def operation(client: TelegramClient):
        max_id = await _fetch_read_outbox_max_id(client, user_id)
        updated = mark_outgoing_read_up_to(slot, user_id, max_id)
        data = load_inbox(slot)
        conv = data.get("conversations", {}).get(str(user_id))
        if conv:
            inferred = infer_outgoing_read_from_thread(conv)
            if inferred:
                save_inbox(slot, data)
                updated = updated or inferred
        return updated

    try:
        if telegram_client.is_login_exclusive(slot):
            return []
        return await telegram_client.run_dm_operation(slot, operation)
    except Exception as e:
        logger.debug("sync_read_receipts %s %s: %s", slot, user_id, e)
        return []


async def attach_handlers(slot: str, client: TelegramClient) -> None:
    """Register private-DM listeners (incoming + outgoing) on an existing client."""
    if slot not in ACCOUNTS:
        return
    prev = _handler_clients.get(slot)
    if slot in _handlers_attached and prev is client:
        return
    if slot in _handlers_attached:
        detach_handlers(slot, prev)

    def _make_incoming(s: str):
        async def handler(event: events.NewMessage.Event) -> None:
            await _on_incoming_message(s, event)
        return handler

    def _make_outgoing(s: str):
        async def handler(event: events.NewMessage.Event) -> None:
            await _on_outgoing_message(s, event)
        return handler

    def _make_read_outbox(s: str):
        async def handler(event: events.MessageRead.Event) -> None:
            await _on_message_read_outbox(s, event)
        return handler

    from telethon.tl.types import UpdatePhoneCall

    from services.phone_call_service import make_phone_call_handler

    handler_in = _make_incoming(slot)
    handler_out = _make_outgoing(slot)
    handler_read = _make_read_outbox(slot)
    handler_phone = make_phone_call_handler(slot, client)
    client.add_event_handler(handler_in, events.NewMessage(incoming=True))
    client.add_event_handler(handler_out, events.NewMessage(outgoing=True))
    client.add_event_handler(handler_read, events.MessageRead(inbox=False))
    client.add_event_handler(handler_phone, events.Raw(types=[UpdatePhoneCall]))
    _handlers_attached.add(slot)
    _handler_clients[slot] = client
    _handler_refs[slot] = {
        "incoming": handler_in,
        "outgoing": handler_out,
        "read_outbox": handler_read,
        "phone_call": handler_phone,
    }
    logger.info("DM inbox listeners attached for %s", slot)


def detach_handlers(slot: str, client: TelegramClient | None = None) -> None:
    refs = _handler_refs.pop(slot, None)
    if refs and client is not None:
        for handler in refs.values():
            try:
                client.remove_event_handler(handler)
            except Exception:
                pass
    _handlers_attached.discard(slot)


async def inbox_on_client_connected(slot: str, client: TelegramClient) -> None:
    if not _is_logged_in(slot):
        return
    # Prefer dedicated string-session listener (avoids duplicate events + SQLite lock).
    existing = _listener_clients.get(slot)
    if existing is not None:
        try:
            if existing.is_connected():
                return
        except Exception:
            pass
    await attach_handlers(slot, client)


async def inbox_on_client_disconnected(slot: str) -> None:
    client = telegram_client.get_client_ref(slot)
    detach_handlers(slot, client)


def _telegram_msg_timestamp(msg) -> str:
    dt = getattr(msg, "date", None)
    if dt is None:
        from core.dm_store import _now_iso

        return _now_iso()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _telegram_msg_text(msg) -> str:
    from core.dm_media import media_placeholder, message_media_meta

    text = (msg.message or "").strip()
    if text:
        return text
    meta = message_media_meta(msg)
    if meta:
        return meta["placeholder"]
    return ""


def _peer_meta_from_entity(entity: User) -> dict:
    from core.dm_filter import _peer_meta

    return _peer_meta(entity)


INBOX_INITIAL_SYNC_LIMIT = 200
INBOX_OLDER_BATCH_LIMIT = 100


async def _sync_conversation_with_client(
    client: TelegramClient,
    slot: str,
    user_id: int,
    *,
    limit: int = INBOX_INITIAL_SYNC_LIMIT,
    max_id: int | None = None,
    touch_crm: bool = True,
) -> tuple[list[dict], int]:
    from services.block_service import assert_not_blocked

    try:
        assert_not_blocked(slot, int(user_id))
    except Exception:
        return []

    last_inbound: dict | None = None
    entity = await client.get_entity(int(user_id))
    if not isinstance(entity, User) or getattr(entity, "bot", False):
        return []
    meta = _peer_meta_from_entity(entity)
    collected: list = []
    iter_kw: dict = {"limit": int(limit)}
    if max_id is not None and int(max_id) > 0:
        iter_kw["max_id"] = int(max_id)
    async for msg in client.iter_messages(entity, **iter_kw):
        collected.append(msg)
    collected.reverse()
    created_records: list[dict] = []
    from core.dm_media import message_media_meta

    for msg in collected:
        media_meta = message_media_meta(msg)
        text = _telegram_msg_text(msg)
        if not text and not media_meta:
            continue
        direction = "out" if bool(getattr(msg, "out", False)) else "in"
        status = "delivered" if direction == "out" else "received"
        _conv, record, created = append_message(
            slot,
            user_id=meta["user_id"],
            username=meta["username"],
            name=meta["name"],
            text=text,
            direction=direction,
            telegram_id=int(msg.id),
            status=status,
            increment_unread=direction == "in",
            account_id=slot,
            timestamp=_telegram_msg_timestamp(msg),
            media=bool(media_meta),
            media_type=media_meta.get("media_type") if media_meta else None,
        )
        if created:
            created_records.append(record)
            if direction == "in":
                last_inbound = record
    if touch_crm and last_inbound:
        from services.crm_service import touch_from_message

        data = load_inbox(slot)
        conv = data.get("conversations", {}).get(str(user_id)) or {}
        touch_from_message(
            slot,
            int(user_id),
            direction="in",
            name=conv.get("name") or "",
            username=conv.get("username") or "",
        )
        mark_all_outgoing_read(slot, int(user_id))
    return created_records, len(collected)


async def _finalize_sync_broadcast(slot: str, user_id: int, new_records: list[dict]) -> None:
    if not new_records:
        return
    from services.crm_service import enrich_conversation

    data = load_inbox(slot)
    conv = data.get("conversations", {}).get(str(user_id)) or {}
    summary = enrich_conversation(slot, _conversation_summary(conv))
    for record in new_records:
        event = "new_message" if record.get("direction") == "in" else "outgoing_message"
        await _broadcast_inbox(slot, event, conversation=summary, message=record)
    await _broadcast_daily_stats()


async def _ensure_string_session_exported(slot: str) -> bool:
    from core.dm_string_session import load_string_session, run_with_string_session, save_string_session

    if load_string_session(slot):
        return True
    try:

        async def grab(client: TelegramClient) -> None:
            save_string_session(slot, client)

        await run_with_string_session(slot, grab)
        if load_string_session(slot):
            return True
    except Exception as e:
        logger.debug("export string session %s: %s", slot, e)
    try:

        async def grab(client: TelegramClient) -> None:
            save_string_session(slot, client)

        await telegram_client.run_dm_operation(
            slot, grab, attempts=2, attach_inbox_handlers=False
        )
    except Exception:
        pass
    return bool(load_string_session(slot))


async def _run_sync_with_client(
    slot: str,
    operation: Callable[[TelegramClient], Awaitable[list[dict]]],
) -> list[dict]:
    from core.dm_string_session import run_with_string_session

    await _ensure_string_session_exported(slot)
    try:
        return await run_with_string_session(slot, operation)
    except Exception as e:
        logger.debug("string session sync %s: %s", slot, e)
    ref = telegram_client.get_client_ref(slot)
    if ref is not None:
        try:
            if ref.is_connected():
                return await operation(ref)
        except Exception:
            pass
    async def wrapped(client: TelegramClient) -> list[dict]:
        return await operation(client)

    return await telegram_client.run_dm_operation(
        slot, wrapped, attempts=4, attach_inbox_handlers=False
    )


async def sync_conversation_from_telegram(
    slot: str,
    user_id: int,
    *,
    limit: int = INBOX_INITIAL_SYNC_LIMIT,
) -> list[dict]:
    """
    Pull recent private messages from Telegram into the local inbox store.
    Backfill when live listeners were offline (session release, reload, etc.).
    """
    if not _is_logged_in(slot):
        return []
    if telegram_client.is_login_exclusive(slot):
        return []

    async def operation(client: TelegramClient) -> list[dict]:
        created, _fetched = await _sync_conversation_with_client(
            client, slot, int(user_id), limit=limit, touch_crm=True
        )
        return created

    try:
        new_records = await _run_sync_with_client(slot, operation)
    except Exception as e:
        logger.warning("sync_conversation %s %s: %s", slot, user_id, e)
        new_records = []

    await _finalize_sync_broadcast(slot, int(user_id), new_records)
    return new_records


async def sync_older_messages_from_telegram(
    slot: str,
    user_id: int,
    *,
    before_telegram_id: int,
    limit: int = INBOX_OLDER_BATCH_LIMIT,
) -> dict:
    """Fetch messages older than before_telegram_id from Telegram into the local store."""
    empty = {"added": 0, "fetched": 0, "has_more": False}
    if not _is_logged_in(slot) or telegram_client.is_login_exclusive(slot):
        return empty
    before = int(before_telegram_id)
    if before <= 0:
        return empty

    fetched_count = 0

    async def operation(client: TelegramClient) -> list[dict]:
        nonlocal fetched_count
        created, fetched_count = await _sync_conversation_with_client(
            client,
            slot,
            int(user_id),
            limit=limit,
            max_id=before,
            touch_crm=False,
        )
        return created

    try:
        new_records = await _run_sync_with_client(slot, operation)
    except Exception as e:
        logger.warning("sync_older %s %s: %s", slot, user_id, e)
        return empty

    await _finalize_sync_broadcast(slot, int(user_id), new_records)
    lim = int(limit)
    return {
        "added": len(new_records),
        "fetched": int(fetched_count),
        "has_more": int(fetched_count) >= lim,
    }


async def sync_stored_conversations(
    slot: str,
    *,
    per_chat_limit: int = 8,
    max_chats: int = 12,
) -> int:
    """Light refresh of stored threads (used by inbox list polling)."""
    if not _is_logged_in(slot) or telegram_client.is_login_exclusive(slot):
        return 0
    data = load_inbox(slot)
    convs = list((data.get("conversations") or {}).values())
    convs.sort(key=lambda c: c.get("last_message_at") or "", reverse=True)
    targets = convs[:max_chats]
    if not targets:
        return 0

    async def operation(client: TelegramClient):
        total: list[dict] = []
        for conv in targets:
            uid = conv.get("user_id")
            if uid is None:
                continue
            try:
                added, _fetched = await _sync_conversation_with_client(
                    client,
                    slot,
                    int(uid),
                    limit=per_chat_limit,
                    touch_crm=False,
                )
                if added:
                    total.extend(added)
                    await _finalize_sync_broadcast(slot, int(uid), added)
            except Exception as e:
                logger.debug("sync_stored %s %s: %s", slot, uid, e)
        return total

    try:
        created = await _run_sync_with_client(slot, operation)
        return len(created)
    except Exception as e:
        logger.debug("sync_stored_conversations %s: %s", slot, e)
        return 0


async def ensure_inbox_listener(slot: str) -> None:
    """Dedicated DM listener on StringSession (independent of worker SQLite)."""
    if not _is_logged_in(slot) or telegram_client.is_login_exclusive(slot):
        return
    from core.dm_string_session import connect_inbox_listener, load_string_session

    if not load_string_session(slot):
        if not await _ensure_string_session_exported(slot):
            return

    prev = _listener_clients.get(slot)
    if prev is not None:
        try:
            if prev.is_connected() and slot in _handlers_attached:
                return
        except Exception:
            pass
        detach_handlers(slot, prev)
        try:
            await prev.disconnect()
        except Exception:
            pass

    client = await connect_inbox_listener(slot)
    if client is None:
        return
    _listener_clients[slot] = client
    await attach_handlers(slot, client)
    logger.info("DM inbox listener (string session) active for %s", slot)


async def suspend_all_for_login() -> None:
    """Stop all inbox listeners while OTP login runs (any slot)."""
    for slot in list(ACCOUNTS.keys()):
        await suspend_for_login(slot)


async def suspend_for_login(slot: str) -> None:
    """Stop inbox listener and cancel refresh so OTP login can open the SQLite session."""
    prev = _listener_refresh_tasks.pop(slot, None)
    if prev is not None and not prev.done():
        prev.cancel()
    client = _listener_clients.pop(slot, None)
    if client is not None:
        detach_handlers(slot, client)
        try:
            await client.disconnect()
        except Exception:
            pass
    _listener_clients.pop(slot, None)


def schedule_inbox_listener_refresh(slot: str) -> None:
    prev = _listener_refresh_tasks.get(slot)
    if prev is not None and not prev.done():
        prev.cancel()

    async def _run() -> None:
        await asyncio.sleep(1.0)
        try:
            await ensure_inbox_listener(slot)
        except Exception as e:
            logger.debug("inbox listener refresh %s: %s", slot, e)

    _listener_refresh_tasks[slot] = asyncio.create_task(_run())


async def run_dm_send(
    slot: str,
    user_id: int,
    text: str,
    *,
    sent_by: str | None = None,
    operator_name: str | None = None,
    reply_to_message_id: int | None = None,
) -> dict:
    """Send a DM from this account slot (manual or Karthik auto-reply)."""
    from core.dm_store import _sender_display_name

    sb = (sent_by or "manual").strip().lower()
    if sb not in {"manual", "ai_approved", "ai", "operator"}:
        sb = "manual"
    display = _sender_display_name(sb, operator_name=operator_name)
    text = (text or "").strip()
    if not text:
        raise ValueError("Message text is required")
    if not _is_logged_in(slot):
        raise RuntimeError(f"{slot} is not logged in")

    from services.block_service import assert_not_blocked

    assert_not_blocked(slot, int(user_id))

    async def operation(client: TelegramClient):
        entity = await client.get_entity(int(user_id))
        if not isinstance(entity, User) or getattr(entity, "bot", False):
            raise ValueError("Not a private user chat")
        send_kwargs: dict = {}
        if reply_to_message_id is not None:
            rid = int(reply_to_message_id)
            if rid > 0:
                send_kwargs["reply_to"] = rid
        sent = await client.send_message(entity, text, **send_kwargs)
        username = (getattr(entity, "username", None) or "").strip()
        first = (getattr(entity, "first_name", None) or "").strip()
        last = (getattr(entity, "last_name", None) or "").strip()
        name = " ".join(p for p in (first, last) if p).strip() or username or str(user_id)
        conv, record, _created = append_message(
            slot,
            user_id=int(user_id),
            username=username,
            name=name,
            text=text,
            direction="out",
            telegram_id=sent.id,
            status="sent",
            increment_unread=False,
            account_id=slot,
            sent_by=sb,
            sender_name=display,
            ai=(sb == "ai"),
        )
        return conv, record

    async def wrapped(client: TelegramClient):
        await attach_handlers(slot, client)
        return await operation(client)

    try:
        conv, record = await telegram_client.run_dm_operation(slot, wrapped)
        await sync_conversation_from_telegram(slot, int(user_id), limit=50)
    except Exception:
        await _broadcast_inbox(
            slot,
            "message_status",
            conversation={"user_id": int(user_id)},
            message={
                "user_id": int(user_id),
                "account_id": slot,
                "status": "failed",
                "direction": "out",
            },
        )
        raise

    from services.crm_service import enrich_conversation, touch_from_message

    mark_conversation_read(slot, int(user_id))
    conv = load_inbox(slot).get("conversations", {}).get(str(user_id), conv)
    touch_from_message(
        slot,
        int(user_id),
        direction="out",
        name=conv.get("name") or "",
        username=conv.get("username") or "",
    )
    summary = enrich_conversation(slot, _conversation_summary(conv))
    uid = int(user_id)
    await _broadcast_inbox(slot, "reply_sent", conversation=summary, message=record)
    delivered = mark_outbound_delivered(slot, uid, record["id"])
    if delivered:
        record = delivered
        await _broadcast_status(slot, uid, delivered, conversation=summary)
    await _broadcast_daily_stats()
    return {"ok": True, "conversation": conv, "message": record}


async def run_dm_send_media(
    slot: str,
    user_id: int,
    file_path: str,
    *,
    caption: str = "",
    filename: str = "",
    content_type: str = "",
    sent_by: str | None = None,
    operator_name: str | None = None,
    reply_to_message_id: int | None = None,
) -> dict:
    """Send a photo/file/voice DM from this account slot."""
    import os
    import shutil

    from core.dm_media import (
        classify_outbound_upload,
        ext_for_upload,
        media_cache_path,
        media_placeholder,
        message_media_meta,
    )
    from core.dm_store import _sender_display_name

    if not file_path or not os.path.isfile(file_path):
        raise ValueError("Attachment file is missing")
    size = os.path.getsize(file_path)
    if size <= 0:
        raise ValueError("Attachment file is empty")
    from core.dm_media import OUTBOUND_UPLOAD_MAX_BYTES

    if size > OUTBOUND_UPLOAD_MAX_BYTES:
        raise ValueError("Attachment too large (max 25 MB)")

    sb = (sent_by or "manual").strip().lower()
    if sb not in {"manual", "ai_approved", "ai", "operator"}:
        sb = "manual"
    display = _sender_display_name(sb, operator_name=operator_name)
    caption = (caption or "").strip()
    upload_info = classify_outbound_upload(filename, content_type)
    media_type = upload_info["media_type"]
    if not _is_logged_in(slot):
        raise RuntimeError(f"{slot} is not logged in")

    from services.block_service import assert_not_blocked

    assert_not_blocked(slot, int(user_id))

    async def operation(client: TelegramClient):
        import asyncio

        from core.dm_media import resolve_outbound_voice_path

        entity = await client.get_entity(int(user_id))
        if not isinstance(entity, User) or getattr(entity, "bot", False):
            raise ValueError("Not a private user chat")
        send_path, temp_voice_path, send_filename = await asyncio.to_thread(
            resolve_outbound_voice_path,
            file_path,
            filename,
            content_type,
        )
        send_kwargs: dict = {}
        if reply_to_message_id is not None:
            rid = int(reply_to_message_id)
            if rid > 0:
                send_kwargs["reply_to"] = rid
        if upload_info.get("voice_note"):
            send_kwargs["voice_note"] = True
        if upload_info.get("force_document"):
            send_kwargs["force_document"] = True
        try:
            sent = await client.send_file(
                entity,
                send_path,
                caption=caption or None,
                **send_kwargs,
            )
            meta = message_media_meta(sent) if sent else None
            if meta and meta.get("media_type"):
                media_type_final = meta["media_type"]
            else:
                media_type_final = media_type
            placeholder = media_placeholder(media_type_final)
            display_text = caption or placeholder
            username = (getattr(entity, "username", None) or "").strip()
            first = (getattr(entity, "first_name", None) or "").strip()
            last = (getattr(entity, "last_name", None) or "").strip()
            name = " ".join(p for p in (first, last) if p).strip() or username or str(user_id)
            conv, record, _created = append_message(
                slot,
                user_id=int(user_id),
                username=username,
                name=name,
                text=display_text,
                direction="out",
                telegram_id=sent.id,
                status="sent",
                increment_unread=False,
                account_id=slot,
                sent_by=sb,
                sender_name=display,
                ai=(sb == "ai"),
                media=True,
                media_type=media_type_final,
            )
            ext = ext_for_upload(send_filename, content_type, media_type_final)
            cache_path = media_cache_path(slot, int(user_id), int(sent.id), ext)
            try:
                shutil.copy2(send_path, cache_path)
            except OSError as e:
                logger.warning("outbound media cache copy %s: %s", slot, e)
            return conv, record
        finally:
            if temp_voice_path and temp_voice_path != file_path and os.path.isfile(temp_voice_path):
                try:
                    os.remove(temp_voice_path)
                except OSError:
                    pass

    async def wrapped(client: TelegramClient):
        await attach_handlers(slot, client)
        return await operation(client)

    try:
        conv, record = await telegram_client.run_dm_operation(slot, wrapped)
        await sync_conversation_from_telegram(slot, int(user_id), limit=50)
    except Exception:
        await _broadcast_inbox(
            slot,
            "message_status",
            conversation={"user_id": int(user_id)},
            message={
                "user_id": int(user_id),
                "account_id": slot,
                "status": "failed",
                "direction": "out",
            },
        )
        raise

    from services.crm_service import enrich_conversation, touch_from_message

    mark_conversation_read(slot, int(user_id))
    conv = load_inbox(slot).get("conversations", {}).get(str(user_id), conv)
    touch_from_message(
        slot,
        int(user_id),
        direction="out",
        name=conv.get("name") or "",
        username=conv.get("username") or "",
    )
    summary = enrich_conversation(slot, _conversation_summary(conv))
    uid = int(user_id)
    await _broadcast_inbox(slot, "reply_sent", conversation=summary, message=record)
    delivered = mark_outbound_delivered(slot, uid, record["id"])
    if delivered:
        record = delivered
        await _broadcast_status(slot, uid, delivered, conversation=summary)
    await _broadcast_daily_stats()
    return {"ok": True, "conversation": conv, "message": record}


async def run_dm_edit(
    slot: str,
    user_id: int,
    message_id: int,
    text: str,
) -> dict:
    """Edit an outbound Telegram message and update local inbox storage."""
    from core.dm_store import load_inbox, patch_message_text

    uid = int(user_id)
    mid = int(message_id)
    clean = (text or "").strip()
    if not clean:
        raise ValueError("Message text is required")
    if not _is_logged_in(slot):
        raise RuntimeError(f"{slot} is not logged in")

    data = load_inbox(slot) or {}
    conv = (data.get("conversations") or {}).get(str(uid)) or {}
    stored = next(
        (m for m in (conv.get("messages") or []) if int(m.get("id") or 0) == mid),
        None,
    )
    if not stored:
        raise ValueError("Message not found")
    if stored.get("direction") != "out":
        raise ValueError("Only your own messages can be edited")
    if stored.get("status") == "sending":
        raise ValueError("Message is still sending")

    async def operation(client: TelegramClient):
        entity = await client.get_entity(uid)
        if not isinstance(entity, User):
            raise ValueError("Not a private user chat")
        await client.edit_message(entity, mid, clean)
        updated_conv, record = patch_message_text(slot, uid, mid, clean)
        if not updated_conv or not record:
            raise ValueError("Failed to update stored message")
        return updated_conv, record

    async def wrapped(client: TelegramClient):
        await attach_handlers(slot, client)
        return await operation(client)

    conv_out, record = await telegram_client.run_dm_operation(slot, wrapped)
    from services.crm_service import enrich_conversation

    summary = enrich_conversation(slot, _conversation_summary(conv_out))
    await _broadcast_inbox(
        slot,
        "message_edited",
        conversation=summary,
        message=record,
    )
    return {
        "ok": True,
        "conversation": conv_out,
        "message": record,
        "unchanged": (stored.get("text") or "").strip() == clean,
    }


async def run_dm_delete_message(
    slot: str,
    user_id: int,
    message_id: int,
) -> dict:
    """Delete an outbound Telegram message and remove it from local storage."""
    from core.dm_store import load_inbox, remove_message

    uid = int(user_id)
    mid = int(message_id)
    if not _is_logged_in(slot):
        raise RuntimeError(f"{slot} is not logged in")

    data = load_inbox(slot) or {}
    conv = (data.get("conversations") or {}).get(str(uid)) or {}
    stored = next(
        (m for m in (conv.get("messages") or []) if int(m.get("id") or 0) == mid),
        None,
    )
    if not stored:
        raise ValueError("Message not found")
    if stored.get("direction") != "out":
        raise ValueError("Only your own messages can be deleted")
    if stored.get("status") == "sending":
        raise ValueError("Message is still sending")

    async def operation(client: TelegramClient):
        entity = await client.get_entity(uid)
        if not isinstance(entity, User):
            raise ValueError("Not a private user chat")
        await client.delete_messages(entity, [mid])
        updated_conv, removed = remove_message(slot, uid, mid)
        if not updated_conv or not removed:
            raise ValueError("Failed to update stored message")
        return updated_conv, removed

    async def wrapped(client: TelegramClient):
        await attach_handlers(slot, client)
        return await operation(client)

    conv_out, removed = await telegram_client.run_dm_operation(slot, wrapped)
    from services.crm_service import enrich_conversation

    summary = enrich_conversation(slot, _conversation_summary(conv_out))
    await _broadcast_inbox(
        slot,
        "message_deleted",
        conversation=summary,
        message={"id": mid, "user_id": uid, "account_id": slot, "direction": "out"},
    )
    return {"ok": True, "conversation": conv_out, "message_id": mid}


async def bootstrap_listeners(*, force: bool = False) -> None:
    """Start string-session DM listeners (does not compete with worker SQLite)."""
    global _bootstrap_done
    if _bootstrap_done and not force:
        return

    await asyncio.sleep(2.0)
    attached = 0
    for slot in ACCOUNTS:
        if not _is_logged_in(slot):
            continue
        if telegram_client.is_login_exclusive(slot):
            logger.info("Inbox listener defer %s: login in progress", slot)
            continue
        try:
            await ensure_inbox_listener(slot)
            if slot in _handlers_attached:
                attached += 1
        except Exception as e:
            logger.info("Inbox listener skip %s: %s", slot, e)
        await asyncio.sleep(1.2)

    _bootstrap_done = True
    logger.info("DM inbox bootstrap done — listeners on %s account(s)", attached)


async def ensure_inbox_listeners() -> None:
    """Re-attach listeners after worker resume or reload (safe to call repeatedly)."""
    await bootstrap_listeners(force=True)


def build_all_inboxes() -> dict:
    slots = {}
    for slot in ACCOUNTS:
        if _is_logged_in(slot):
            slots[slot] = build_slot_payload(slot)
    return {"slots": slots}


def get_combined_conversations() -> list[dict]:
    combined = []
    for slot in ACCOUNTS:
        if not _is_logged_in(slot):
            continue
        for c in build_slot_payload(slot)["conversations"]:
            combined.append({**c, "account_id": slot})
    combined.sort(key=lambda x: x.get("last_message_at") or "", reverse=True)
    return combined


async def mark_read(slot: str, user_id: int) -> None:
    """Clear unread badge and stop reply-waiting timer when the agent opens the thread."""
    from core.dm_store import list_conversations

    uid = int(user_id)
    mark_conversation_read(slot, uid)

    try:
        from services import crm_service
        from services.block_service import is_blocked

        if not is_blocked(slot, uid):
            lead = crm_service.get_lead(slot, uid)
            inbox_row = None
            data = load_inbox(slot)
            conv = (data.get("conversations") or {}).get(str(uid))
            if conv:
                inbox_row = {
                    "user_id": conv.get("user_id"),
                    "username": conv.get("username") or "",
                    "name": conv.get("name") or "",
                    "last_message": conv.get("last_message") or "",
                    "last_message_at": conv.get("last_message_at"),
                    "unread_count": 0,
                }
            if not lead and inbox_row:
                lead = crm_service.default_lead_for_conversation(slot, inbox_row)
            if lead:
                lead = crm_service.ensure_reply_timestamps(slot, uid) or lead
                if crm_service._unanswered_elapsed_seconds(lead) is not None:
                    await crm_service.mark_reply_handled(slot, uid)
                    return
    except Exception as e:
        logger.debug("mark_read reply_handled: %s", e)

    summary = None
    for c in list_conversations(slot):
        if int(c.get("user_id") or 0) == uid:
            summary = {**c, "unread_count": 0}
            break
    if summary:
        from services.crm_service import enrich_conversation

        summary = enrich_conversation(slot, summary)
    else:
        summary = {"user_id": uid, "unread_count": 0}
    await _broadcast_inbox(slot, "read", conversation=summary)


async def delete_conversation(slot: str, user_id: int) -> dict:
    """Remove stored inbox thread, CRM lead, calls, and cached media (not Telegram chat)."""
    from core.call_store import delete_call_records
    from core.crm_store import delete_lead
    from core.dm_media import clear_media_cache_for_user
    from core.dm_store import delete_conversation as _delete_stored

    uid = int(user_id)
    if not _delete_stored(slot, uid):
        return {"status": "error", "message": "Conversation not found"}
    clear_media_cache_for_user(slot, uid)
    delete_lead(slot, uid)
    delete_call_records(slot, uid)
    await _broadcast_inbox(
        slot,
        "conversation_deleted",
        conversation={"user_id": uid, "account_id": slot},
    )
    return {"status": "ok", "slot": slot, "user_id": uid}


async def ensure_inbox_media_file(
    slot: str,
    user_id: int,
    message_id: int,
) -> tuple[str, str] | None:
    """Download Telegram media into cache if needed; return (path, mime_type)."""
    import os

    from core.dm_media import (
        find_cached_media,
        guess_download_ext,
        media_cache_dir,
        media_cache_path,
        message_media_meta,
    )

    from core.dm_media import is_probably_text_attachment, read_text_attachment

    async def promote_text_attachment(path: str) -> None:
        if not is_probably_text_attachment(path):
            return
        body = read_text_attachment(path)
        if not body:
            return
        from core.dm_store import patch_message_text_by_telegram_id

        record = patch_message_text_by_telegram_id(
            slot, int(user_id), int(message_id), body,
        )
        try:
            os.remove(path)
        except OSError:
            pass
        if record:
            await _finalize_sync_broadcast(slot, int(user_id), [record])

    hit = find_cached_media(slot, int(user_id), int(message_id))
    if hit:
        path, _mime = hit
        if is_probably_text_attachment(path):
            await promote_text_attachment(path)
            return None
        return hit

    if not _is_logged_in(slot):
        return None

    async def operation(client: TelegramClient) -> tuple[str, str] | None:
        entity = await client.get_entity(int(user_id))
        raw = await client.get_messages(entity, ids=int(message_id))
        if isinstance(raw, list):
            msg = raw[0] if raw else None
        else:
            msg = raw
        if not msg or not getattr(msg, "media", None):
            return None
        meta = message_media_meta(msg)
        media_type = (meta or {}).get("media_type") or "media"
        ext = guess_download_ext(msg, media_type)
        out_path = media_cache_path(slot, user_id, message_id, ext)

        from core.dm_media import finalize_cached_download

        async def save_download(target: str, *, thumb: int | None = None) -> str | None:
            try:
                result = await client.download_media(
                    msg, file=target, thumb=thumb,
                )
            except Exception as e:
                logger.warning(
                    "download_media %s %s %s thumb=%s: %s",
                    slot, user_id, message_id, thumb, e,
                )
                return None
            path = result if isinstance(result, str) and os.path.isfile(result) else target
            if path and os.path.isfile(path) and os.path.getsize(path) > 0:
                return path
            try:
                data = await client.download_media(msg, bytes, thumb=thumb)
                if data:
                    with open(target, "wb") as fh:
                        fh.write(data)
                    return target
            except Exception as e2:
                logger.debug(
                    "download_media bytes %s %s %s thumb=%s: %s",
                    slot, user_id, message_id, thumb, e2,
                )
            return None

        def finalize(path: str | None) -> tuple[str, str] | None:
            return finalize_cached_download(path, media_type)

        if media_type == "sticker":
            for thumb in (-1, 0):
                thumb_path = media_cache_path(
                    slot, user_id, message_id, f".thumb{abs(thumb)}.webp",
                )
                saved = await save_download(thumb_path, thumb=thumb)
                hit = finalize(saved) if saved else None
                if hit:
                    display = media_cache_path(slot, user_id, message_id, ".webp")
                    try:
                        if saved != display:
                            os.replace(saved, display)
                        for name in os.listdir(media_cache_dir(slot)):
                            if not name.startswith(f"{int(user_id)}_{int(message_id)}"):
                                continue
                            extra = os.path.join(media_cache_dir(slot), name)
                            if extra != display and os.path.isfile(extra):
                                os.remove(extra)
                    except OSError as e:
                        logger.debug("sticker cache tidy %s: %s", slot, e)
                    fin = finalize(display) or hit
                    if fin:
                        return fin
            saved = await save_download(out_path)
            hit = finalize(saved) if saved else None
            if hit:
                return hit
            return None

        saved = await save_download(out_path)
        if saved and is_probably_text_attachment(saved):
            await promote_text_attachment(saved)
            return None
        hit = finalize(saved) if saved else None
        if hit:
            return hit
        return None

    from core.dm_string_session import run_with_string_session

    await _ensure_string_session_exported(slot)
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            result = await run_with_string_session(slot, operation, attempts=2)
            if result:
                return result
        except Exception as e:
            last_err = e
            err = str(e).lower()
            if "database is locked" in err or "event loop" in err:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            logger.debug("string session media %s: %s", slot, e)
            break
    try:
        return await telegram_client.run_dm_operation(
            slot, operation, attempts=4, attach_inbox_handlers=False,
        )
    except Exception as e:
        logger.warning("ensure_inbox_media %s: %s", slot, e or last_err)
        return None
