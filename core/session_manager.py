"""Per-account session lifecycle — create, validate, purge on logout."""

from __future__ import annotations

import os

from core.account_logging import account_log
from core.account_lifecycle import purge_all_session_artifacts
from core.config import ACCOUNTS, BASE_DIR


class SessionManager:
    """Wraps Telethon session files — no cross-account session reuse."""

    def session_path(self, account_id: str) -> str:
        self._validate(account_id)
        return os.path.join(BASE_DIR, ACCOUNTS[account_id]) + ".session"

    def _validate(self, account_id: str) -> None:
        if account_id not in ACCOUNTS:
            raise ValueError(f"Invalid account_id: {account_id}")

    def exists(self, account_id: str) -> bool:
        return os.path.exists(self.session_path(account_id))

    async def validate_session(self, account_id: str) -> bool:
        """True if session file exists and Telethon can connect as authorized."""
        self._validate(account_id)
        if not self.exists(account_id):
            return False
        from core import telegram_client

        try:
            client = await telegram_client.get_client(account_id)
            return bool(await client.is_user_authorized())
        except Exception as e:
            account_log(account_id, f"Session validation failed: {e}", level="warning")
            return False

    async def release(self, account_id: str, *, wait: float = 1.0) -> None:
        from core import telegram_client

        await telegram_client.release_session(account_id, wait=wait)

    async def delete_session(self, account_id: str) -> None:
        """Full purge — prevents stale session reuse after logout."""
        self._validate(account_id)
        from core import telegram_client

        await telegram_client.abandon_slot_session(account_id)
        try:
            await telegram_client.release_session(account_id, wait=0.5)
        except Exception:
            pass
        try:
            await telegram_client.release_login_client(account_id, wait=0.25)
        except Exception:
            pass
        purge_all_session_artifacts(account_id)
        account_log(account_id, "Session deleted", level="info")

    async def commit_login(self, account_id: str, session_string: str) -> None:
        from core import telegram_client

        await telegram_client.commit_login_session(account_id, session_string)
        account_log(account_id, "Session committed after login", level="info")

    async def prepare_for_login(self, account_id: str) -> None:
        from core import telegram_client

        await telegram_client.quiesce_slot_for_login(account_id)


session_manager = SessionManager()
