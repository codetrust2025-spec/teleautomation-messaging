"""Async pub/sub event bus — multiple isolated subscriber channels."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

from core import broadcast
from events.event_types import EventType, SubscriberChannel

EventHandler = Callable[[str, EventType, dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._channels: dict[SubscriberChannel, list[EventHandler]] = defaultdict(list)
        self._account_handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._on_state_push: Callable[[], Awaitable[None]] | None = None

    def set_state_push(self, cb: Callable[[], Awaitable[None]]) -> None:
        self._on_state_push = cb

    def subscribe(
        self,
        handler: EventHandler,
        *,
        channel: SubscriberChannel | None = None,
        account_id: str | None = None,
    ) -> None:
        if channel is not None:
            self._channels[channel].append(handler)
        if account_id:
            self._account_handlers[account_id].append(handler)

    async def publish(
        self,
        event_type: EventType,
        account_id: str,
        data: dict[str, Any] | None = None,
        *,
        push_state: bool = True,
        broadcast_ws: bool = True,
    ) -> None:
        payload_data = data or {}
        if broadcast_ws:
            await broadcast.broadcast({
                "type": "event",
                "event": event_type.value,
                "account_id": account_id,
                "data": payload_data,
            })

        handlers: list[EventHandler] = []
        for ch_handlers in self._channels.values():
            handlers.extend(ch_handlers)
        handlers.extend(self._account_handlers.get(account_id, []))

        async def _safe(h: EventHandler) -> None:
            try:
                await h(account_id, event_type, payload_data)
            except Exception:
                pass

        if handlers:
            await asyncio.gather(*[_safe(h) for h in handlers], return_exceptions=True)

        if push_state and self._on_state_push:
            try:
                await self._on_state_push()
            except Exception:
                pass


event_bus = EventBus()
