"""Native Telegram voice calls via Telethon RequestCallRequest.

Uses the long-lived inbox listener client for the full call lifecycle so
ConfirmCallRequest runs on the same session that received the answer.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any

from telethon import TelegramClient
from telethon.tl.functions.messages import GetDhConfigRequest
from telethon.tl.functions.phone import ConfirmCallRequest, DiscardCallRequest, RequestCallRequest
from telethon.tl.types import (
    InputPhoneCall,
    PhoneCall,
    PhoneCallAccepted,
    PhoneCallDiscarded,
    PhoneCallProtocol,
    PhoneCallWaiting,
    User,
)
from telethon.utils import get_input_user

from core import broadcast

logger = logging.getLogger(__name__)

_outbound: dict[str, dict[str, Any]] = {}
_call_log_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "crm",
    "voice_call.log",
)

_CALL_PROTOCOL = PhoneCallProtocol(
    min_layer=92,
    max_layer=92,
    udp_p2p=True,
    udp_reflector=True,
    library_versions=["2.4.4", "3.0.0"],
)


def _log_call(msg: str, *args) -> None:
    line = msg % args if args else msg
    logger.info(line)
    try:
        os.makedirs(os.path.dirname(_call_log_path), exist_ok=True)
        with open(_call_log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {line}\n")
    except Exception:
        pass


def _g_a_to_bytes(g_a_int: int) -> bytes:
    """Telegram expects 256-byte little-endian g_a for call confirm."""
    return int(g_a_int).to_bytes(256, byteorder="little", signed=False)


def _integer_to_bytes(integer: int) -> bytes:
    return int.to_bytes(
        integer,
        length=(integer.bit_length() + 8 - 1) // 8,
        byteorder="big",
        signed=False,
    )


def _calc_fingerprint(key: int) -> int:
    return int.from_bytes(
        bytes(hashlib.sha1(_integer_to_bytes(key)).digest()[-8:]),
        "little",
        signed=True,
    )


async def _get_dh_config(client: TelegramClient):
    resp = await client(GetDhConfigRequest(version=0, random_length=256))
    p = int.from_bytes(resp.p, "big")
    g = resp.g
    return resp, p, g


def _rand_bytes(dh_random: bytes, length: int = 256) -> bytes:
    return bytes(x ^ y for x, y in zip(os.urandom(length), dh_random))


def _persist_crypto(session_id: str, *, a: int, p: int, g_a: bytes, call_id: int, access_hash: int) -> None:
    if not session_id:
        return
    from core.voice_call_store import update_session

    update_session(
        session_id,
        tg_call_a=int(a),
        tg_call_p=int(p),
        tg_call_g_a_b64=base64.b64encode(g_a).decode("ascii"),
        telegram_call_id=int(call_id),
        tg_call_access_hash=int(access_hash),
    )


def _load_crypto_from_session(session_id: str) -> dict[str, Any]:
    from core.voice_call_store import get_session

    row = get_session(session_id) or {}
    return _crypto_from_row(row, session_id=session_id)


def _crypto_from_row(row: dict, *, session_id: str = "") -> dict[str, Any]:
    g_a_b64 = row.get("tg_call_g_a_b64") or ""
    g_a = b""
    if g_a_b64:
        try:
            g_a = base64.b64decode(g_a_b64.encode("ascii"))
        except Exception:
            g_a = b""
    sid = session_id or str(row.get("id") or "")
    return {
        "a": int(row.get("tg_call_a") or 0),
        "p": int(row.get("tg_call_p") or 0),
        "g_a": g_a,
        "call_id": int(row.get("telegram_call_id") or 0),
        "access_hash": int(row.get("tg_call_access_hash") or 0),
        "session_id": sid,
    }


def _hydrate_outbound_state(slot: str, call_id: int) -> dict[str, Any]:
    """Restore DH keys from memory or disk — required for ConfirmCall after reconnect."""
    state = dict(_outbound.get(slot) or {})
    if state.get("a") and state.get("g_a"):
        return state

    session_id = str(state.get("session_id") or "")
    if session_id:
        loaded = _load_crypto_from_session(session_id)
        if loaded.get("a"):
            state.update(loaded)
            state.setdefault("call_id", call_id)
            _outbound[slot] = state
            return state

    from core.voice_call_store import find_session_by_telegram_call_id

    session = find_session_by_telegram_call_id(slot, call_id)
    if not session:
        return state

    loaded = _crypto_from_row(session, session_id=str(session.get("id") or ""))
    if not loaded.get("a"):
        return state

    state = {
        "call_id": call_id,
        "access_hash": int(loaded.get("access_hash") or 0),
        "user_id": int(session.get("user_id") or 0),
        "name": session.get("lead_name") or "",
        "username": session.get("lead_username") or "",
        "session_id": str(session.get("id") or ""),
        "ringing": True,
        "confirmed": False,
        **loaded,
    }
    _outbound[slot] = state
    logger.info("hydrated outbound crypto slot=%s call_id=%s session=%s", slot, call_id, state.get("session_id"))
    return state


def _state_for_slot(slot: str) -> dict[str, Any]:
    state = dict(_outbound.get(slot) or {})
    if state.get("a") and state.get("g_a"):
        return state
    session_id = str(state.get("session_id") or "")
    if session_id:
        loaded = _load_crypto_from_session(session_id)
        if loaded.get("a"):
            state.update(loaded)
            _outbound[slot] = state
    return state


def is_outbound_active(slot: str, user_id: int | None = None) -> bool:
    active = _outbound.get(slot) or {}
    if not active.get("ringing") and not active.get("call_id"):
        return False
    if user_id is None:
        return True
    return int(active.get("user_id") or 0) == int(user_id)


async def _resolve_call_client(slot: str) -> TelegramClient:
    """Worker SQLite session — single stable connection for ring + confirm."""
    from core import telegram_client
    from services import dm_inbox_service
    from services.phone_call_service import attach_phone_call_handler

    await dm_inbox_service.suspend_listener_for_call(slot)
    client = await telegram_client.get_client(slot)
    if not client.is_connected():
        raise RuntimeError(f"{slot}: worker session offline — start the account worker first")
    attach_phone_call_handler(slot, client)
    return client


def _resume_listener(slot: str) -> None:
    try:
        from services import dm_inbox_service

        dm_inbox_service.resume_listener_after_call(slot)
    except Exception:
        pass


async def _call_keepalive(slot: str) -> None:
    """Keep worker Telethon connected while outbound call is active."""
    from core import telegram_client

    while is_outbound_active(slot):
        try:
            client = telegram_client.get_client_ref(slot)
            if client and client.is_connected():
                await client.get_me()
        except Exception:
            pass
        await asyncio.sleep(8)


async def _broadcast_telegram_event(
    slot: str,
    event: str,
    *,
    user_id: int = 0,
    call_id: int = 0,
    session_id: str = "",
    extra: dict | None = None,
) -> None:
    payload: dict[str, Any] = {
        "type": "voice_call",
        "event": event,
        "slot": slot,
        "user_id": int(user_id),
        "call": {
            "call_id": call_id,
            "callType": "telegram",
            "session_id": session_id,
            **(extra or {}),
        },
    }
    if session_id:
        from core.voice_call_store import get_session

        session = get_session(session_id)
        if session:
            payload["session"] = session
    await broadcast.broadcast(payload)
    logger.info("telegram call event %s slot=%s user=%s call_id=%s", event, slot, user_id, call_id)


async def request_native_call(
    slot: str,
    user_id: int,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    """Ring the lead via Telethon and complete ConfirmCall when they answer."""
    from services.block_service import assert_not_blocked
    from services.call_service import resolve_contact
    from services.dm_inbox_service import _resolve_user_entity

    assert_not_blocked(slot, int(user_id))
    contact = resolve_contact(slot, int(user_id))

    active = _state_for_slot(slot)
    if active.get("call_id"):
        same_user = int(active.get("user_id") or 0) == int(user_id)
        same_session = not session_id or str(active.get("session_id") or "") == session_id
        if same_user and same_session and active.get("ringing") and not active.get("confirmed"):
            if session_id and not active.get("session_id"):
                active["session_id"] = session_id
                _outbound[slot] = active
            return {
                "ok": True,
                "reused": True,
                "call_id": active.get("call_id"),
                "access_hash": active.get("access_hash"),
                "user_id": int(user_id),
                "call_type": "telegram",
                "session_id": session_id or active.get("session_id") or "",
            }
        await discard_native_call(slot)

    try:
        from services import tgcalls_service

        tgcalls_service.drop_slot(slot)
    except Exception:
        pass

    client = await _resolve_call_client(slot)
    entity = await _resolve_user_entity(client, slot, int(user_id))
    if not isinstance(entity, User) or getattr(entity, "bot", False):
        raise ValueError("Not a private user chat")
    input_user = get_input_user(entity)

    dh_resp, p, g = await _get_dh_config(client)
    a = 0
    while not (1 < a < p - 1):
        a = int.from_bytes(_rand_bytes(dh_resp.random), "little")
    g_a = pow(g, a, p)
    g_a_bytes = _g_a_to_bytes(g_a)
    g_a_hash = hashlib.sha256(g_a_bytes).digest()
    random_id = random.randint(0, 0x7FFFFFFF - 1)

    result = await client(
        RequestCallRequest(
            user_id=input_user,
            random_id=random_id,
            g_a_hash=g_a_hash,
            protocol=_CALL_PROTOCOL,
        )
    )
    phone_call = getattr(result, "phone_call", None)
    if not isinstance(phone_call, PhoneCallWaiting):
        raise RuntimeError(f"Unexpected call response: {type(phone_call).__name__}")

    call_id = int(phone_call.id)
    access_hash = int(getattr(phone_call, "access_hash", 0) or 0)

    _outbound[slot] = {
        "call_id": call_id,
        "access_hash": access_hash,
        "user_id": int(user_id),
        "name": contact.get("name") or "",
        "username": contact.get("username") or "",
        "session_id": session_id,
        "a": a,
        "p": p,
        "g_a": g_a_bytes,
        "ringing": True,
        "confirmed": False,
    }
    _persist_crypto(session_id, a=a, p=p, g_a=g_a_bytes, call_id=call_id, access_hash=access_hash)

    _log_call("ring %s -> user=%s call_id=%s session=%s", slot, user_id, call_id, session_id)

    asyncio.create_task(_call_keepalive(slot), name=f"call_keepalive_{slot}")

    await _broadcast_telegram_event(
        slot,
        "telegram_ringing",
        user_id=int(user_id),
        call_id=call_id,
        session_id=session_id,
        extra={"name": contact.get("name") or ""},
    )
    logger.info("Telegram call ringing %s -> %s call_id=%s", slot, user_id, call_id)
    return {
        "ok": True,
        "reused": False,
        "call_id": call_id,
        "access_hash": access_hash,
        "user_id": int(user_id),
        "call_type": "telegram",
        "session_id": session_id,
        "engine": "telethon_ring",
    }


async def _confirm_outbound_call(
    slot: str,
    client: TelegramClient,
    call: PhoneCallAccepted,
) -> None:
    call_id = int(call.id)
    state = _hydrate_outbound_state(slot, call_id)
    if int(state.get("call_id") or 0) not in (0, call_id):
        logger.warning(
            "call_id mismatch on accept slot=%s expected=%s got=%s — continuing",
            slot,
            state.get("call_id"),
            call_id,
        )
    state["call_id"] = call_id
    _outbound[slot] = state
    if state.get("confirmed"):
        return

    a = int(state.get("a") or 0)
    p = int(state.get("p") or 0)
    g_a = state.get("g_a")
    if not a or not p or not g_a:
        _log_call("missing crypto slot=%s call_id=%s session=%s", slot, call_id, state.get("session_id"))
        return

    access_hash = int(getattr(call, "access_hash", 0) or 0) or int(state.get("access_hash") or 0)
    g_b_raw = call.g_b or b""
    key_fingerprint = None
    for endian in ("big", "little"):
        try:
            g_b = int.from_bytes(g_b_raw, endian)
            key = pow(g_b, a, p)
            key_fingerprint = _calc_fingerprint(key)
            break
        except Exception:
            continue
    if key_fingerprint is None:
        _log_call("could not derive call key slot=%s call_id=%s", slot, call_id)
        return

    _log_call("confirm start slot=%s call_id=%s session=%s", slot, call_id, state.get("session_id"))
    try:
        result = await client(
            ConfirmCallRequest(
                peer=InputPhoneCall(id=call_id, access_hash=access_hash),
                g_a=g_a,
                key_fingerprint=key_fingerprint,
                protocol=_CALL_PROTOCOL,
            )
        )
        state["confirmed"] = True
        state["call_id"] = call_id
        state["access_hash"] = access_hash
        state["ringing"] = True
        _outbound[slot] = state
        _log_call("confirm ok slot=%s call_id=%s", slot, call_id)

        phone_call = getattr(result, "phone_call", None)
        if isinstance(phone_call, PhoneCall):
            await _mark_outbound_connected(slot, phone_call)
        else:
            asyncio.create_task(
                _start_post_confirm_media(slot, client, int(state.get("user_id") or 0)),
                name=f"post_confirm_media_{slot}",
            )
    except Exception as e:
        _log_call("confirm failed slot=%s call_id=%s err=%r", slot, call_id, e)
        session_id = str(state.get("session_id") or "")
        _outbound.pop(slot, None)
        await _broadcast_telegram_event(
            slot,
            "telegram_failed",
            user_id=int(state.get("user_id") or 0),
            call_id=call_id,
            session_id=session_id,
            extra={"error": str(e)[:200]},
        )
        if session_id:
            try:
                from services import voice_call_orchestrator

                await voice_call_orchestrator.finish_session(
                    session_id,
                    status="failed",
                    by="system",
                    end_telegram=False,
                )
            except Exception as ex:
                logger.warning("finish failed session %s: %s", session_id, ex)


async def _start_post_confirm_media(slot: str, client: TelegramClient, user_id: int) -> None:
    """Keep call alive with silence PCM after Telethon confirm (prevents instant discard)."""
    if not user_id:
        return
    try:
        from services import tgcalls_service

        await tgcalls_service.pump_silence_for_call(slot, client, user_id)
    except Exception as e:
        _log_call("post-confirm media failed slot=%s user=%s err=%s", slot, user_id, e)


async def _notify_peer_answered(slot: str, call: PhoneCallAccepted) -> None:
    state = _state_for_slot(slot)
    session_id = str(state.get("session_id") or "")
    user_id = int(state.get("user_id") or 0)
    if session_id:
        try:
            from services import voice_call_service

            await voice_call_service.mark_connecting(session_id, by="client")
        except Exception as e:
            logger.warning("mark_connecting for telegram call %s: %s", session_id, e)
    await _broadcast_telegram_event(
        slot,
        "telegram_answered",
        user_id=user_id,
        call_id=int(call.id),
        session_id=session_id,
        extra={"name": state.get("name") or "", "phase": "answered"},
    )


async def _mark_outbound_connected(slot: str, call: PhoneCall) -> None:
    state = _state_for_slot(slot)
    call_id = int(call.id)
    if int(state.get("call_id") or 0) not in (0, call_id):
        return

    now = datetime.now(timezone.utc).isoformat()
    state["connected_at"] = now
    state["call_id"] = call_id
    _outbound[slot] = state

    session_id = str(state.get("session_id") or "")
    user_id = int(state.get("user_id") or 0)

    if session_id:
        try:
            from services import voice_call_service

            await voice_call_service.mark_active(session_id, by="client")
        except Exception as e:
            logger.warning("mark_active for telegram call %s: %s", session_id, e)

    await _broadcast_telegram_event(
        slot,
        "telegram_active",
        user_id=user_id,
        call_id=call_id,
        session_id=session_id,
        extra={"name": state.get("name") or "", "phase": "connected"},
    )
    logger.info("Native Telegram call connected slot=%s call_id=%s", slot, call_id)


async def discard_native_call(
    slot: str,
    *,
    call_id: int | None = None,
    access_hash: int | None = None,
    reason_missed: bool = True,
) -> None:
    active = _state_for_slot(slot)
    cid = int(call_id or active.get("call_id") or 0)
    ah = int(access_hash if access_hash is not None else active.get("access_hash") or 0)
    if not cid or not ah:
        _outbound.pop(slot, None)
        return

    client = await _resolve_call_client(slot)

    from telethon.tl.types import PhoneCallDiscardReasonHangup, PhoneCallDiscardReasonMissed

    reason = PhoneCallDiscardReasonMissed() if reason_missed else PhoneCallDiscardReasonHangup()
    try:
        await client(
            DiscardCallRequest(
                peer=InputPhoneCall(id=cid, access_hash=ah),
                reason=reason,
                duration=0,
                connection_id=0,
            )
        )
    except Exception as e:
        logger.warning("discard native call %s: %s", slot, e)
    finally:
        if int((_outbound.get(slot) or {}).get("call_id") or 0) == cid:
            _outbound.pop(slot, None)
        _resume_listener(slot)


async def handle_outbound_call_update(
    slot: str,
    client: TelegramClient,
    call: PhoneCallWaiting | PhoneCallAccepted | PhoneCall | PhoneCallDiscarded,
) -> None:
    logger.info(
        "outbound call update slot=%s type=%s id=%s",
        slot,
        type(call).__name__,
        getattr(call, "id", None),
    )
    _log_call(
        "update slot=%s type=%s id=%s",
        slot,
        type(call).__name__,
        getattr(call, "id", None),
    )

    if isinstance(call, PhoneCallAccepted):
        await _notify_peer_answered(slot, call)
        await _confirm_outbound_call(slot, client, call)
        return

    if isinstance(call, PhoneCall):
        await _mark_outbound_connected(slot, call)
        return

    if isinstance(call, PhoneCallDiscarded):
        active = _outbound.get(slot) or {}
        if int(active.get("call_id") or 0) == int(call.id):
            session_id = str(active.get("session_id") or "")
            user_id = int(active.get("user_id") or 0)
            _outbound.pop(slot, None)
            reason_name = type(call.reason).__name__
            _log_call("discarded slot=%s call_id=%s reason=%s", slot, int(call.id), reason_name)
            if session_id:
                try:
                    from services import voice_call_orchestrator

                    await voice_call_orchestrator.on_telegram_remote_end(
                        slot,
                        session_id,
                        reason=reason_name,
                    )
                except Exception as ex:
                    logger.warning("remote end session %s: %s", session_id, ex)
            await _broadcast_telegram_event(
                slot,
                "telegram_ended",
                user_id=user_id,
                call_id=int(call.id),
                session_id=session_id,
                extra={"reason": reason_name},
            )
            _resume_listener(slot)
        return

    if isinstance(call, PhoneCallWaiting):
        # Outbound state is set in request_native_call — do not overwrite DH keys here.
        return
