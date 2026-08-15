"""Native Telegram P2P calls via py-tgcalls (full VoIP media path)."""

from __future__ import annotations

import asyncio
import logging
import os
import wave
from typing import Any

from telethon import TelegramClient

from core import broadcast

logger = logging.getLogger(__name__)

_call_log_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "crm",
    "voice_call.log",
)


def _log_call(msg: str, *args) -> None:
    line = msg % args if args else msg
    logger.info(line)
    try:
        from datetime import datetime, timezone

        os.makedirs(os.path.dirname(_call_log_path), exist_ok=True)
        with open(_call_log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {line}\n")
    except Exception:
        pass

_slot_tg: dict[str, Any] = {}
_outbound: dict[str, dict[str, Any]] = {}
_handlers_attached: set[str] = set()

_SILENCE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "crm",
    "silence.wav",
)


def _ensure_silence_wav() -> str:
    os.makedirs(os.path.dirname(_SILENCE_PATH), exist_ok=True)
    min_bytes = 48000 * 2 * 120  # ~120s hold
    if os.path.isfile(_SILENCE_PATH) and os.path.getsize(_SILENCE_PATH) >= min_bytes:
        return _SILENCE_PATH
    with wave.open(_SILENCE_PATH, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"\x00\x00" * 48000 * 120)
    return _SILENCE_PATH


def is_outbound_active(slot: str, user_id: int | None = None) -> bool:
    active = _outbound.get(slot) or {}
    if not active.get("running"):
        return False
    if user_id is None:
        return True
    return int(active.get("user_id") or 0) == int(user_id)


async def notify_peer_answered(slot: str, user_id: int) -> None:
    """Lead picked up — signaling only, media may still be connecting."""
    uid = int(user_id)
    active = _outbound.get(slot) or {}
    if int(active.get("user_id") or 0) != uid or not active.get("running"):
        return
    if active.get("answered_sent"):
        return
    active["answered_sent"] = True
    _outbound[slot] = active
    session_id = str(active.get("session_id") or "")
    if session_id:
        try:
            from services import voice_call_service

            await voice_call_service.mark_connecting(session_id, by="client")
        except Exception:
            pass
    await _broadcast(slot, "telegram_answered", user_id=uid, session_id=session_id)
    _log_call("answered slot=%s user=%s session=%s", slot, uid, session_id)
    call_py = _slot_tg.get(slot)
    if call_py is not None:
        try:
            pc = getattr(call_py, "private_calls", None) or []
            _log_call("private_calls slot=%s count=%s", slot, len(pc))
        except Exception as e:
            _log_call("private_calls check failed slot=%s err=%s", slot, e)
    asyncio.create_task(
        _connect_watchdog(slot, uid, session_id),
        name=f"tgcalls_watchdog_{slot}_{uid}",
    )


async def _connect_watchdog(slot: str, user_id: int, session_id: str) -> None:
    """Fail loudly if media never connects after answer."""
    await asyncio.sleep(25)
    active = _outbound.get(slot) or {}
    if int(active.get("user_id") or 0) != int(user_id) or not active.get("running"):
        return
    if active.get("active_sent"):
        return
    _log_call("connect timeout slot=%s user=%s session=%s", slot, user_id, session_id)
    active["running"] = False
    active["ended_sent"] = True
    _outbound.pop(slot, None)
    call_py = _slot_tg.get(slot)
    if call_py:
        try:
            if asyncio.iscoroutinefunction(call_py.leave_call):
                await call_py.leave_call(int(user_id))
            else:
                await asyncio.to_thread(call_py.leave_call, int(user_id))
        except Exception:
            pass
    if session_id:
        from core.tg_audio_bridge import close_bridge

        await close_bridge(session_id)
        try:
            from services import voice_call_orchestrator

            await voice_call_orchestrator.finish_session(
                session_id,
                status="failed",
                by="system",
                end_telegram=False,
            )
        except Exception:
            pass
    await _broadcast(
        slot,
        "telegram_failed",
        user_id=int(user_id),
        session_id=session_id,
        extra={
            "error": (
                "Voice connection timed out — if Sridhar/account5 is logged into "
                "Telegram on a phone, log out there first (only one device can hold the call)."
            ),
        },
    )
    _resume_listener(slot)


async def notify_peer_connected(slot: str, user_id: int) -> None:
    uid = int(user_id)
    active = _outbound.get(slot) or {}
    if int(active.get("user_id") or 0) != uid or not active.get("running"):
        return
    if active.get("active_sent"):
        return
    active["active_sent"] = True
    _outbound[slot] = active
    session_id = str(active.get("session_id") or "")
    await _mark_session_active(session_id)
    await _broadcast(slot, "telegram_active", user_id=uid, session_id=session_id)
    _log_call("active slot=%s user=%s session=%s", slot, uid, session_id)


async def notify_peer_ended(slot: str, user_id: int) -> None:
    uid = int(user_id)
    active = _outbound.get(slot) or {}
    if int(active.get("user_id") or 0) != uid:
        return
    if active.get("ended_sent"):
        return
    session_id = str(active.get("session_id") or "")
    active["running"] = False
    active["ended_sent"] = True
    _outbound.pop(slot, None)
    if session_id:
        from core.tg_audio_bridge import close_bridge

        await close_bridge(session_id)
        try:
            from services import voice_call_orchestrator

            await voice_call_orchestrator.on_telegram_remote_end(slot, session_id)
        except Exception:
            pass
    await _broadcast(slot, "telegram_ended", user_id=uid, session_id=session_id)
    logger.info("tgcalls peer ended slot=%s user=%s", slot, uid)
    _resume_listener(slot)


def _resume_listener(slot: str) -> None:
    try:
        from services import dm_inbox_service

        dm_inbox_service.resume_listener_after_call(slot)
    except Exception as e:
        logger.debug("resume listener %s: %s", slot, e)


async def _broadcast(
    slot: str,
    event: str,
    *,
    user_id: int = 0,
    session_id: str = "",
    call_id: int = 0,
    extra: dict[str, Any] | None = None,
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
    logger.info("tgcalls %s slot=%s user=%s session=%s", event, slot, user_id, session_id)


def _attach_update_handlers(slot: str, call_py: Any) -> None:
    if slot in _handlers_attached:
        return
    from pytgcalls import filters as fl
    from pytgcalls.types import ChatUpdate, Direction, Device, StreamFrames

    @call_py.on_update(
        fl.chat_update(
            ChatUpdate.Status.DISCARDED_CALL
            | ChatUpdate.Status.BUSY_CALL
            | ChatUpdate.Status.CLOSED_VOICE_CHAT
        )
    )
    async def _on_call_end(_py: Any, update: ChatUpdate) -> None:
        uid = int(getattr(update, "chat_id", 0) or 0)
        active = _outbound.get(slot) or {}
        if uid and int(active.get("user_id") or 0) not in (0, uid):
            return
        session_id = str(active.get("session_id") or "")
        _log_call("call end slot=%s user=%s session=%s", slot, uid, session_id)
        active["running"] = False
        _outbound.pop(slot, None)
        if session_id:
            from core.tg_audio_bridge import close_bridge

            await close_bridge(session_id)
        if not active.get("ended_sent"):
            await _broadcast(slot, "telegram_ended", user_id=uid, session_id=session_id)
        _resume_listener(slot)

    @call_py.on_update(
        fl.stream_frame(directions=Direction.INCOMING, devices=Device.MICROPHONE)
    )
    async def _on_lead_audio(_py: Any, update: StreamFrames) -> None:
        uid = int(getattr(update, "chat_id", 0) or 0)
        active = _outbound.get(slot) or {}
        if int(active.get("user_id") or 0) not in (0, uid) or not active.get("running"):
            return
        session_id = str(active.get("session_id") or "")
        if not active.get("active_sent"):
            await notify_peer_connected(slot, uid)
        if not session_id:
            return
        from core.tg_audio_bridge import forward_lead_pcm

        for frame in getattr(update, "frames", []) or []:
            pcm = getattr(frame, "frame", b"") or b""
            if pcm:
                await forward_lead_pcm(session_id, pcm)

    @call_py.on_update(fl.chat_update(ChatUpdate.Status.INCOMING_CALL))
    async def _on_incoming(_py: Any, update: ChatUpdate) -> None:
        uid = int(getattr(update, "chat_id", 0) or 0)
        logger.info("tgcalls incoming call slot=%s user=%s", slot, uid)

    _handlers_attached.add(slot)


async def ensure_tgcalls(slot: str, client: TelegramClient) -> Any:
    from pytgcalls import PyTgCalls

    existing = _slot_tg.get(slot)
    if existing is not None:
        prev = getattr(existing, "mtproto_client", None)
        if prev is client:
            return existing
        logger.info("PyTgCalls rebinding %s to worker client", slot)
        drop_slot(slot)

    call_py = PyTgCalls(client)
    _attach_update_handlers(slot, call_py)
    if asyncio.iscoroutinefunction(call_py.start):
        await call_py.start()
    else:
        await asyncio.to_thread(call_py.start)
    _slot_tg[slot] = call_py
    logger.info("PyTgCalls started for %s", slot)
    return call_py


async def _resolve_client(slot: str) -> TelegramClient:
    """Worker SQLite session for VoIP — no inbox handlers (PyTgCalls owns the connection)."""
    from core import telegram_client
    from services import dm_inbox_service

    await dm_inbox_service.suspend_listener_for_call(slot)
    client = await telegram_client.get_client(slot, attach_inbox=False)
    if not client.is_connected():
        raise RuntimeError(f"{slot}: worker session offline")
    return client


async def _mark_session_active(session_id: str) -> None:
    if not session_id:
        return
    try:
        from services import voice_call_service

        await voice_call_service.mark_active(session_id, by="client")
    except Exception as e:
        logger.warning("mark_active session=%s: %s", session_id, e)


async def pump_silence_for_call(slot: str, client: TelegramClient, user_id: int) -> None:
    """Send silence frames on an already-confirmed Telethon call."""
    from pytgcalls.types import Device
    from services import telegram_call_service as tcs

    uid = int(user_id)
    call_py = await ensure_tgcalls(slot, client)
    chunk = b"\x00\x00" * 480
    logger.info("tgcalls media pump start slot=%s user=%s", slot, uid)
    sent = 0
    for _ in range(600):
        if not tcs.is_outbound_active(slot) and not is_outbound_active(slot):
            break
        try:
            if asyncio.iscoroutinefunction(call_py.send_frame):
                await call_py.send_frame(uid, Device.MICROPHONE, chunk)
            else:
                await asyncio.to_thread(call_py.send_frame, uid, Device.MICROPHONE, chunk)
            sent += 1
            if sent == 5:
                await notify_peer_connected(slot, uid)
        except Exception:
            if sent == 0:
                await asyncio.sleep(0.05)
                continue
            break
        await asyncio.sleep(0.02)
    logger.info("tgcalls silence pump done slot=%s user=%s sent=%s", slot, uid, sent)


async def _silence_pcm_pump(call_py: Any, slot: str, uid: int, stop: asyncio.Event) -> None:
    from pytgcalls.types import Device

    chunk = b"\x00\x00" * 480
    ok = 0
    while not stop.is_set():
        active = _outbound.get(slot) or {}
        if not active.get("running"):
            break
        try:
            if asyncio.iscoroutinefunction(call_py.send_frame):
                await call_py.send_frame(uid, Device.MICROPHONE, chunk)
            else:
                await asyncio.to_thread(call_py.send_frame, uid, Device.MICROPHONE, chunk)
            ok += 1
            if ok == 1:
                _log_call("first audio frame slot=%s user=%s", slot, uid)
            if ok == 5 and not active.get("active_sent"):
                await notify_peer_connected(slot, uid)
        except Exception as e:
            if ok == 0:
                await asyncio.sleep(0.02)
                continue
            _log_call("send_frame stopped slot=%s user=%s sent=%s err=%s", slot, uid, ok, e)
            break
        await asyncio.sleep(0.01)


async def _run_outgoing_call(
    slot: str,
    call_py: Any,
    user_id: int,
    session_id: str,
) -> None:
    import contextlib
    from pytgcalls.types import CallConfig, ExternalMedia, MediaStream
    from pytgcalls.types.raw import AudioParameters

    uid = int(user_id)
    stop = asyncio.Event()
    params = AudioParameters(bitrate=48000, channels=1)
    config = CallConfig(timeout=7200)
    stream = MediaStream(ExternalMedia.AUDIO, params)
    _log_call(
        "play start slot=%s user=%s session=%s mode=external_media+pump",
        slot,
        uid,
        session_id,
    )
    pump = asyncio.create_task(
        _silence_pcm_pump(call_py, slot, uid, stop),
        name=f"tgcalls_pcm_{slot}_{uid}",
    )
    try:
        if asyncio.iscoroutinefunction(call_py.play):
            await call_py.play(uid, stream, config=config)
        else:
            await asyncio.to_thread(call_py.play, uid, stream, config)
    except Exception as e:
        _log_call("play failed slot=%s user=%s err=%s", slot, uid, e)
        logger.error("tgcalls play failed slot=%s user=%s: %s", slot, uid, e, exc_info=True)
        active = _outbound.get(slot) or {}
        if (
            int(active.get("user_id") or 0) == uid
            and active.get("running")
            and not active.get("ended_sent")
        ):
            active["ended_sent"] = True
            await _broadcast(slot, "telegram_ended", user_id=uid, session_id=session_id)
            _outbound.pop(slot, None)
    finally:
        stop.set()
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        _resume_listener(slot)
    _log_call("play returned slot=%s user=%s", slot, uid)


async def start_outgoing_call(
    slot: str,
    user_id: int,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    """Place native Telegram call with working VoIP media (py-tgcalls)."""
    uid = int(user_id)
    active = _outbound.get(slot) or {}
    if int(active.get("user_id") or 0) == uid and active.get("running"):
        return {
            "ok": True,
            "reused": True,
            "user_id": uid,
            "session_id": session_id or active.get("session_id") or "",
            "call_type": "telegram",
        }

    client = await _resolve_client(slot)
    from services.dm_inbox_service import detach_handlers
    from services.phone_call_service import attach_phone_call_handler

    detach_handlers(slot, client)
    attach_phone_call_handler(slot, client)
    call_py = await ensure_tgcalls(slot, client)

    _outbound[slot] = {
        "user_id": uid,
        "session_id": session_id,
        "running": True,
        "active_sent": False,
        "answered_sent": False,
    }
    if session_id:
        from core.tg_audio_bridge import open_bridge

        await open_bridge(session_id, slot=slot, user_id=uid)
    await _broadcast(slot, "telegram_ringing", user_id=uid, session_id=session_id)
    _log_call("ring slot=%s user=%s session=%s", slot, uid, session_id)

    asyncio.create_task(
        _run_outgoing_call(slot, call_py, uid, session_id),
        name=f"tgcalls_call_{slot}_{uid}",
    )

    return {
        "ok": True,
        "reused": False,
        "user_id": uid,
        "session_id": session_id,
        "call_type": "telegram",
        "engine": "pytgcalls",
    }


async def end_outgoing_call(slot: str, user_id: int | None = None) -> None:
    call_py = _slot_tg.get(slot)
    active = _outbound.get(slot) or {}
    uid = int(user_id if user_id is not None else active.get("user_id") or 0)
    session_id = str(active.get("session_id") or "")
    if not uid:
        _outbound.pop(slot, None)
        _resume_listener(slot)
        return
    active["running"] = False
    _outbound[slot] = active
    if call_py:
        try:
            if asyncio.iscoroutinefunction(call_py.leave_call):
                await call_py.leave_call(uid)
            else:
                await asyncio.to_thread(call_py.leave_call, uid)
        except Exception as e:
            logger.warning("tgcalls leave_call %s %s: %s", slot, uid, e)
    _outbound.pop(slot, None)
    if session_id:
        from core.tg_audio_bridge import close_bridge

        await close_bridge(session_id)
    if session_id and not active.get("ended_sent"):
        active["ended_sent"] = True
        await _broadcast(slot, "telegram_ended", user_id=uid, session_id=session_id)
    _resume_listener(slot)


def drop_slot(slot: str) -> None:
    _slot_tg.pop(slot, None)
    _outbound.pop(slot, None)
    _handlers_attached.discard(slot)
