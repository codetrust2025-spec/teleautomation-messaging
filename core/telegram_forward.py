"""Shared native Telegram forward helpers."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError

DEFAULT_MAX_FLOOD_WAIT = 300


async def native_forward_message(
    client: TelegramClient,
    dest: str | int,
    source_peer: str,
    source_message_id: int,
    *,
    max_flood_wait: int = DEFAULT_MAX_FLOOD_WAIT,
    flood_retries: int = 1,
) -> None:
    """
    Forward one message using Telethon (message id + from_peer).
    Retries up to flood_retries times after FloodWait.
    """
    if not source_peer or source_message_id <= 0:
        raise ValueError("source_peer and source_message_id required")

    attempts = max(1, int(flood_retries) + 1)
    last_flood: FloodWaitError | None = None

    for attempt in range(attempts):
        try:
            await client.forward_messages(
                dest,
                source_message_id,
                from_peer=source_peer,
            )
            return
        except FloodWaitError as e:
            last_flood = e
            if attempt >= attempts - 1:
                break
            wait_s = min(max(int(e.seconds), 1), max_flood_wait)
            await asyncio.sleep(wait_s)

    if last_flood is not None:
        raise last_flood
    raise RuntimeError("native_forward_message failed without exception")


def parse_target_ids(target_ids: list | None) -> set[int]:
    """Parse group ids from API/UI (supports negative Telegram supergroup ids)."""
    out: set[int] = set()
    for raw in target_ids or []:
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            out.add(int(raw))
            continue
        s = str(raw).strip()
        if not s:
            continue
        try:
            out.add(int(s))
        except ValueError:
            continue
    return out
