"""WebSocket broadcast — transport only, no business logic."""

from typing import Any, List

from fastapi import WebSocket

active_connections: List[WebSocket] = []
connection_profiles: dict[WebSocket, dict[str, Any]] = {}


async def broadcast(data: dict) -> None:
    dead = []
    for ws in active_connections:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connection_profiles.pop(ws, None)
        if ws in active_connections:
            active_connections.remove(ws)
