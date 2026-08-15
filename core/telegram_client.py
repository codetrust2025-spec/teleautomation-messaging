"""Per-slot Telegram client — one session file, one connection at a time."""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Awaitable, Callable, TypeVar

from telethon import TelegramClient

T = TypeVar("T")

from core.config import ACCOUNTS, API_HASH, API_ID, BASE_DIR, STATE_DIR

_clients: dict[str, TelegramClient | None] = {slot: None for slot in ACCOUNTS}
_login_clients: dict[str, TelegramClient | None] = {}
_login_session_strings: dict[str, str] = {}
_locks: dict[str, asyncio.Lock] = {}
_login_locks: dict[str, asyncio.Lock] = {}
_login_exclusive: set[str] = set()


def _main_session_base(slot: str) -> str:
    return os.path.join(BASE_DIR, ACCOUNTS[slot])


def _staging_session_base(slot: str) -> str:
    os.makedirs(os.path.join(STATE_DIR, slot), exist_ok=True)
    return os.path.join(STATE_DIR, slot, "login_staging")


def _session_paths(base: str) -> list[str]:
    return [
        base + ".session",
        base + ".session-wal",
        base + ".session-shm",
        base + ".session-journal",
    ]


def _remove_session_files(base: str) -> None:
    for path in _session_paths(base):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _copy_session_files(src_base: str, dst_base: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        src = src_base + ".session" + suffix
        dst = dst_base + ".session" + suffix
        if os.path.exists(src):
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass


def _backup_main_session_files(slot: str) -> None:
    """Move main SQLite session aside so OTP login does not open a locked file."""
    main = _main_session_base(slot)
    bak = os.path.join(STATE_DIR, slot, "session_prelogin")
    _remove_session_files(bak)
    for suffix in ("", "-wal", "-shm", "-journal"):
        src = main + ".session" + suffix
        dst = bak + ".session" + suffix
        if os.path.exists(src):
            try:
                os.replace(src, dst)
            except OSError:
                pass


def _write_sqlite_session_from_string(session_str: str, path_base: str) -> None:
    from telethon.sessions import SQLiteSession, StringSession

    src = StringSession(session_str)
    _remove_session_files(path_base)
    db = SQLiteSession(path_base)
    db.set_dc(src.dc_id, src.server_address, src.port)
    db.auth_key = src.auth_key
    takeout = getattr(src, "takeout_id", None)
    if takeout is not None:
        db.takeout_id = takeout
    db.save()


def remember_login_session_string(slot: str, session_str: str) -> None:
    if session_str:
        _login_session_strings[slot] = str(session_str)


def backup_main_session_for_login(slot: str) -> None:
    _backup_main_session_files(slot)


def purge_main_session_files(slot: str) -> None:
    """Remove main session so worker cannot reopen it during OTP (backup is in session_prelogin)."""
    _remove_session_files(_main_session_base(slot))


async def abandon_slot_session(slot: str) -> None:
    """Drop client refs without closing SQLite (avoids database is locked during login)."""
    _ensure_slot(slot)
    async with _slot_lock(slot):
        _clients[slot] = None
    async with _login_lock(slot):
        _login_clients.pop(slot, None)


async def abandon_all_sessions() -> None:
    for slot in list(ACCOUNTS.keys()):
        await abandon_slot_session(slot)
    await asyncio.sleep(2.0)


async def quiesce_slot_for_login(slot: str, *, wait: float = 12.0) -> None:
    """
    Prepare ONE slot for OTP — other accounts keep running.
    Uses StringSession only; does not close SQLite aggressively (avoids lock errors).
    """
    from core.account_lifecycle import purge_all_session_artifacts
    from core.config import SESSION_LOCK_RECONNECT_WAIT
    from core.worker_persistence import mark_stopped

    set_login_exclusive(slot, True)
    mark_stopped(slot)

    try:
        from services.dm_inbox_service import suspend_for_login

        await suspend_for_login(slot)
    except Exception:
        pass

    try:
        from services.account_manager import manager

        w = manager.get_worker(slot)
        w.stop()
        task = w.state.task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=wait)
            except Exception:
                pass
    except Exception:
        pass

    try:
        await asyncio.wait_for(release_session(slot, wait=1.0), timeout=4.0)
    except Exception:
        pass

    await abandon_slot_session(slot)
    await asyncio.sleep(SESSION_LOCK_RECONNECT_WAIT)

    try:
        backup_main_session_for_login(slot)
    except Exception:
        pass
    purge_all_session_artifacts(slot)

    for attempt in range(4):
        main = _main_session_base(slot)
        if not os.path.exists(main + ".session"):
            break
        await asyncio.sleep(1.5)

    await asyncio.sleep(0.5)


async def finalize_login_exclusive(slot: str) -> None:
    """Clear login-in-progress flag after OTP completes or aborts."""
    set_login_exclusive(slot, False)
    await release_login_client(slot, wait=0.25)


def _ensure_slot(slot: str) -> None:
    if slot not in ACCOUNTS:
        raise ValueError(f"Invalid slot: {slot}")
    if slot not in _clients:
        _clients[slot] = None
    if slot not in _locks:
        _locks[slot] = asyncio.Lock()


def _slot_lock(slot: str) -> asyncio.Lock:
    _ensure_slot(slot)
    return _locks[slot]


def _login_lock(slot: str) -> asyncio.Lock:
    """Separate from worker lock — OTP never blocks on group-posting SQLite."""
    _ensure_slot(slot)
    if slot not in _login_locks:
        _login_locks[slot] = asyncio.Lock()
    return _login_locks[slot]


def sync_slots() -> None:
    for slot in ACCOUNTS:
        _ensure_slot(slot)


def is_login_exclusive(slot: str) -> bool:
    return slot in _login_exclusive


def any_login_exclusive() -> bool:
    return bool(_login_exclusive)


def set_login_exclusive(slot: str, exclusive: bool) -> None:
    _ensure_slot(slot)
    if exclusive:
        _login_exclusive.add(slot)
    else:
        _login_exclusive.discard(slot)


async def _disconnect_unlocked(slot: str) -> None:
    client = _clients.get(slot)
    if client:
        try:
            from services.dm_inbox_service import inbox_on_client_disconnected

            await inbox_on_client_disconnected(slot)
        except Exception:
            pass
        try:
            await client.disconnect()
        except Exception:
            pass
    _clients[slot] = None


def _is_db_locked(exc: BaseException) -> bool:
    return "database is locked" in str(exc).lower()


async def _close_session_db(client: TelegramClient | None) -> None:
    """Close SQLite connection under Telethon session (helps release file locks)."""
    if client is None:
        return
    try:
        from telethon.sessions import SQLiteSession

        sess = client.session
        if isinstance(sess, SQLiteSession):
            conn = getattr(sess, "_conn", None)
            if conn is not None:
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
                sess._conn = None
    except Exception:
        pass


async def release_session(slot: str, *, wait: float = 1.0) -> None:
    """Disconnect and wait for SQLite session file (Windows needs a short delay)."""
    _ensure_slot(slot)
    async with _slot_lock(slot):
        client = _clients.get(slot)
        await _disconnect_unlocked(slot)
        await _close_session_db(client)
    if wait > 0:
        await asyncio.sleep(wait)
    if not is_login_exclusive(slot):
        try:
            from services.dm_inbox_service import schedule_inbox_listener_refresh

            schedule_inbox_listener_refresh(slot)
        except Exception:
            pass


def _needs_reconnect(client: TelegramClient | None) -> bool:
    if client is None:
        return True
    try:
        return not client.is_connected()
    except Exception:
        return True


async def get_client(slot: str) -> TelegramClient:
    if is_login_exclusive(slot):
        raise RuntimeError(f"{slot} session reserved for login — try again in a moment")
    _ensure_slot(slot)
    async with _slot_lock(slot):
        return await _ensure_connected_unlocked(slot)


async def _ensure_connected_unlocked(slot: str) -> TelegramClient:
    if is_login_exclusive(slot):
        raise RuntimeError(f"{slot} session reserved for login")
    client = _clients.get(slot)
    if not _needs_reconnect(client):
        return client  # type: ignore[return-value]
    if client is not None:
        await _disconnect_unlocked(slot)
        await asyncio.sleep(0.35)
    client = TelegramClient(ACCOUNTS[slot], API_ID, API_HASH)
    await _connect_with_retry(slot, client)
    _apply_session_wal(client)
    _clients[slot] = client
    try:
        from core.dm_string_session import save_string_session

        save_string_session(slot, client)
    except Exception:
        pass
    try:
        from services.dm_inbox_service import inbox_on_client_connected

        await inbox_on_client_connected(slot, client)
    except Exception:
        pass
    return client


def _apply_session_wal(client: TelegramClient) -> None:
    """Reduce SQLite 'database is locked' on Windows (best-effort)."""
    try:
        from telethon.sessions import SQLiteSession

        sess = client.session
        if isinstance(sess, SQLiteSession) and getattr(sess, "_conn", None):
            sess._conn.execute("PRAGMA journal_mode=WAL")
            sess._conn.execute("PRAGMA synchronous=NORMAL")
            sess._conn.execute("PRAGMA busy_timeout=60000")
            sess._conn.commit()
    except Exception:
        pass


async def reconnect_client(slot: str, *, wait: float | None = None) -> TelegramClient:
    """Force a clean session after disconnect / database is locked."""
    from core.config import SESSION_LOCK_RECONNECT_WAIT

    if wait is None:
        wait = SESSION_LOCK_RECONNECT_WAIT
    await release_session(slot, wait=wait)
    return await get_client(slot)


async def run_dm_operation(
    slot: str,
    operation: Callable[[TelegramClient], Awaitable[T]],
    *,
    attempts: int = 4,
    attach_inbox_handlers: bool = True,
) -> T:
    """Short Telethon op for manual DM replies (shares slot lock with group ops)."""
    if is_login_exclusive(slot):
        raise RuntimeError(f"{slot} session reserved for login")
    _ensure_slot(slot)
    last: BaseException | None = None
    async with _slot_lock(slot):
        for i in range(attempts):
            try:
                client = await _ensure_connected_unlocked(slot)
                if attach_inbox_handlers:
                    try:
                        from services.dm_inbox_service import attach_handlers

                        await attach_handlers(slot, client)
                    except Exception:
                        pass
                return await operation(client)
            except Exception as e:
                last = e
                if not is_session_error(str(e)) or i >= attempts - 1:
                    raise
                await _disconnect_unlocked(slot)
                await _close_session_db(_clients.get(slot))
                await asyncio.sleep(min(8.0, 1.5 * (i + 1)))
    if last:
        raise last
    raise RuntimeError("run_dm_operation failed")


async def run_group_operation(
    slot: str,
    operation: Callable[[TelegramClient], Awaitable[T]],
    *,
    attempts: int = 5,
) -> T:
    """
    Run one group pipeline with slot lock held — prevents disconnect mid-call.
    Retries on session / SQLite errors.
    """
    if is_login_exclusive(slot):
        raise RuntimeError(f"{slot} session reserved for login")
    _ensure_slot(slot)
    last: BaseException | None = None
    async with _slot_lock(slot):
        for i in range(attempts):
            try:
                client = await _ensure_connected_unlocked(slot)
                return await operation(client)
            except Exception as e:
                last = e
                if not is_session_error(str(e)) or i >= attempts - 1:
                    raise
                await _disconnect_unlocked(slot)
                await _close_session_db(_clients.get(slot))
                await asyncio.sleep(min(8.0, 1.5 * (i + 1)))
    if last:
        raise last
    raise RuntimeError("run_group_operation failed")


def is_session_error(message: str) -> bool:
    s = (message or "").lower()
    return "database is locked" in s or "disconnected" in s or "not connected" in s


async def _connect_with_retry(slot: str, client: TelegramClient, attempts: int = 6) -> None:
    last: BaseException | None = None
    for i in range(attempts):
        try:
            await client.connect()
            return
        except Exception as e:
            last = e
            if not _is_db_locked(e) or i >= attempts - 1:
                raise
            await _disconnect_unlocked(slot)
            await asyncio.sleep(0.4 * (i + 1))
    if last:
        raise last


async def disconnect_client(slot: str) -> None:
    async with _slot_lock(slot):
        await _disconnect_unlocked(slot)


def get_client_ref(slot: str) -> TelegramClient | None:
    return _clients.get(slot)


def set_client(slot: str, client: TelegramClient | None) -> None:
    _ensure_slot(slot)
    _clients[slot] = client


async def disconnect_all() -> None:
    for slot in list(ACCOUNTS.keys()):
        await release_session(slot, wait=0.1)


async def release_login_client(slot: str, *, wait: float = 0.5) -> None:
    """Disconnect in-memory OTP client (StringSession — no SQLite file)."""
    _ensure_slot(slot)
    async with _login_lock(slot):
        client = _login_clients.pop(slot, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
            await _close_session_db(client)
    if wait > 0:
        await asyncio.sleep(wait)


async def _open_string_login_client(slot: str) -> TelegramClient:
    """OTP login in RAM only — no SQLite file (avoids database is locked on Windows)."""
    from telethon.sessions import StringSession

    saved = _login_session_strings.get(slot)
    session = StringSession(saved) if saved else StringSession()
    client = TelegramClient(session, API_ID, API_HASH)
    await client.connect()
    _login_clients[slot] = client
    return client


async def connect_for_login(slot: str) -> TelegramClient:
    """OTP connect via StringSession only — does not open session_accountN.session."""
    _ensure_slot(slot)
    async with _login_lock(slot):
        await release_login_client(slot, wait=0.1)
        return await _open_string_login_client(slot)


async def get_login_client(slot: str) -> TelegramClient:
    """Reuse send-otp client; reconnect from saved StringSession if disconnected."""
    _ensure_slot(slot)
    async with _login_lock(slot):
        client = _login_clients.get(slot)
        if client is not None:
            try:
                if client.is_connected():
                    return client
            except Exception:
                pass
            try:
                saved = client.session.save()
                if saved:
                    remember_login_session_string(slot, saved)
            except Exception:
                pass
            await release_login_client(slot, wait=0.35)
        if not _login_session_strings.get(slot):
            from core.login_pending import load_pending

            pending = load_pending(slot)
            if pending and pending.get("session_string"):
                remember_login_session_string(slot, pending["session_string"])
        return await _open_string_login_client(slot)


async def commit_login_session(slot: str) -> None:
    """After OTP success, write auth to main session_accountN SQLite + string session file."""
    _ensure_slot(slot)
    async with _login_lock(slot):
        client = _login_clients.pop(slot, None)
        session_str = _login_session_strings.pop(slot, None)
        if client is not None:
            try:
                saved = client.session.save()
                if saved:
                    session_str = saved
            except Exception:
                pass
            try:
                await client.disconnect()
            except Exception:
                pass
        if not session_str:
            return
        main = _main_session_base(slot)
        _write_sqlite_session_from_string(session_str, main)
        try:
            from telethon.sessions import StringSession

            from core.dm_string_session import save_string_session

            probe = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await probe.connect()
            save_string_session(slot, probe)
            await probe.disconnect()
        except Exception:
            pass
        _remove_session_files(_staging_session_base(slot))


async def run_login_with_retry(
    slot: str,
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 8,
) -> T:
    """Retry OTP Telethon calls on staging session only."""
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return await operation()
        except Exception as e:
            last = e
            if not _is_db_locked(e) or i >= attempts - 1:
                raise
            await release_login_client(slot, wait=min(8.0, 1.0 * (i + 1)))
            async with _login_lock(slot):
                await _open_string_login_client(slot)
    if last:
        raise last
    raise RuntimeError("run_login_with_retry failed")


async def run_with_retry(
    slot: str,
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 6,
) -> T:
    """Retry Telethon calls when SQLite session reports 'database is locked'."""
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return await operation()
        except Exception as e:
            last = e
            if not _is_db_locked(e) or i >= attempts - 1:
                raise
            await release_session(slot, wait=min(8.0, 1.0 * (i + 1)))
    if last:
        raise last
    raise RuntimeError("run_with_retry failed")
