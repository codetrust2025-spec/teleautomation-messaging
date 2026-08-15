"""
In-memory StringSession for inbox sync + live DM listeners.

Uses the same Telegram auth as the main SQLite session but does not open
session_accountN.session, so workers can hold the SQLite file without
blocking inbox reads (fixes 'database is locked' on Windows).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Awaitable, Callable, TypeVar

from telethon import TelegramClient
from telethon.sessions import StringSession

from core.config import ACCOUNTS, API_HASH, API_ID, BASE_DIR, STATE_DIR

logger = logging.getLogger(__name__)

T = TypeVar("T")
_locks: dict[str, asyncio.Lock] = {}


def _path(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, "inbox_string_session.txt")


def save_string_session(slot: str, client: TelegramClient) -> bool:
    try:
        saved = client.session.save()
        if not saved:
            return False
        os.makedirs(os.path.dirname(_path(slot)), exist_ok=True)
        tmp = _path(slot) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(saved)
        os.replace(tmp, _path(slot))
        return True
    except Exception as e:
        logger.debug("save_string_session %s: %s", slot, e)
        return False


def load_string_session(slot: str) -> str | None:
    path = _path(slot)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read().strip()
        return raw or None
    except OSError:
        return None


def _slot_lock(slot: str) -> asyncio.Lock:
    if slot not in _locks:
        _locks[slot] = asyncio.Lock()
    return _locks[slot]


def _snapshot_session_path(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, "inbox_snapshot")


def _prepare_snapshot_session(slot: str) -> str | None:
    """Copy main .session to a snapshot path (read-only inbox sync while worker runs)."""
    try:
        from core import telegram_client

        if telegram_client.is_login_exclusive(slot):
            return None
    except Exception:
        pass
    src = os.path.join(BASE_DIR, f"{ACCOUNTS[slot]}.session")
    if not os.path.exists(src):
        return None
    base = _snapshot_session_path(slot)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    try:
        shutil.copy2(src, base + ".session")
        for suffix in ("-wal", "-shm", "-journal"):
            s = src + suffix
            if os.path.exists(s):
                try:
                    shutil.copy2(s, base + ".session" + suffix)
                except OSError:
                    pass
        return base
    except OSError as e:
        logger.debug("snapshot session %s: %s", slot, e)
        return None


async def _connect_inbox_client(slot: str) -> TelegramClient:
    session_str = load_string_session(slot)
    if session_str:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            return client
        await client.disconnect()

    snap = _prepare_snapshot_session(slot)
    if not snap:
        raise RuntimeError(f"{slot}: no session snapshot")
    client = TelegramClient(snap, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(f"{slot}: snapshot session not authorized")
    save_string_session(slot, client)
    return client


async def run_with_string_session(
    slot: str,
    operation: Callable[[TelegramClient], Awaitable[T]],
    *,
    attempts: int = 3,
) -> T:
    """Inbox Telethon op without opening the worker's locked SQLite session."""
    last: BaseException | None = None
    async with _slot_lock(slot):
        for i in range(attempts):
            client: TelegramClient | None = None
            try:
                client = await _connect_inbox_client(slot)
                return await operation(client)
            except Exception as e:
                last = e
                if i < attempts - 1:
                    await asyncio.sleep(1.0 * (i + 1))
            finally:
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
    if last:
        raise last
    raise RuntimeError(f"{slot}: run_with_string_session failed")


async def connect_inbox_listener(slot: str) -> TelegramClient | None:
    """Long-lived Telethon client for DM events (separate from worker SQLite)."""
    async with _slot_lock(slot):
        try:
            session_str = load_string_session(slot)
            if session_str:
                client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
                await client.connect()
                if await client.is_user_authorized():
                    return client
                await client.disconnect()
            snap = _prepare_snapshot_session(slot)
            if not snap:
                return None
            client = TelegramClient(snap, API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return None
            save_string_session(slot, client)
            return client
        except Exception as e:
            logger.debug("connect_inbox_listener %s: %s", slot, e)
            return None
