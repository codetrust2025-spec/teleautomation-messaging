"""WebRTC signaling relay — in-memory peer routing per call session."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# session_id -> {operator: WebSocket|None, client: WebSocket|None, queue: list}
_rooms: dict[str, dict[str, Any]] = {}
_lock = asyncio.Lock()


async def register_peer(session_id: str, role: str, ws: WebSocket) -> None:
    async with _lock:
        room = _rooms.setdefault(session_id, {"operator": None, "client": None, "queue": []})
        room[role] = ws
        # Flush queued signals to the newly connected peer.
        pending = list(room.get("queue") or [])
        room["queue"] = []
    for item in pending:
        target_role = item.get("target")
        if target_role == role:
            try:
                await ws.send_json(item.get("payload") or {})
            except Exception:
                logger.debug("signaling flush failed session=%s role=%s", session_id, role, exc_info=True)


async def unregister_peer(session_id: str, role: str, ws: WebSocket) -> None:
    async with _lock:
        room = _rooms.get(session_id)
        if not room:
            return
        if room.get(role) is ws:
            room[role] = None
        if not room.get("operator") and not room.get("client"):
            _rooms.pop(session_id, None)


async def relay_signal(
    session_id: str,
    from_role: str,
    payload: dict,
) -> bool:
    to_role = "client" if from_role == "operator" else "operator"
    envelope = {
        "type": "voice",
        "event": "signal",
        "session_id": session_id,
        "from": from_role,
        "signal": payload,
    }
    async with _lock:
        room = _rooms.get(session_id) or {}
        target = room.get(to_role)
        if target is None:
            room.setdefault("queue", []).append({"target": to_role, "payload": envelope})
            if session_id not in _rooms:
                _rooms[session_id] = room
            return False
    try:
        await target.send_json(envelope)
        return True
    except Exception:
        logger.debug("signaling relay failed session=%s", session_id, exc_info=True)
        return False


async def broadcast_state(session_id: str, payload: dict) -> None:
    envelope = {"type": "voice", "event": "state", "session_id": session_id, **payload}
    async with _lock:
        room = _rooms.get(session_id) or {}
        peers = [ws for ws in (room.get("operator"), room.get("client")) if ws is not None]
    for ws in peers:
        try:
            await ws.send_json(envelope)
        except Exception:
            pass
