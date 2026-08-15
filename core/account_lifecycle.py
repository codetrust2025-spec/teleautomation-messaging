"""Login/logout lifecycle — per-slot session and worker cleanup."""

from __future__ import annotations

import os

from core.config import ACCOUNTS, BASE_DIR, STATE_DIR
from core.login_pending import clear_pending


def _main_session_base(slot: str) -> str:
    return os.path.join(BASE_DIR, ACCOUNTS[slot])


def _staging_session_base(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, "login_staging")


def _prelogin_session_base(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, "session_prelogin")


def _session_paths(base: str) -> list[str]:
    return [
        base + ".session",
        base + ".session-wal",
        base + ".session-shm",
        base + ".session-journal",
    ]


def _remove_files(base: str) -> None:
    for path in _session_paths(base):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def purge_all_session_artifacts(slot: str) -> None:
    """Remove every on-disk session artifact for one account slot."""
    if slot not in ACCOUNTS:
        return
    _remove_files(_main_session_base(slot))
    _remove_files(_staging_session_base(slot))
    _remove_files(_prelogin_session_base(slot))
    try:
        from core.dm_string_session import _path as string_session_path

        p = string_session_path(slot)
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass
    clear_pending(slot)
