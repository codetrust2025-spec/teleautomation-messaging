"""Monitor accounts — auto-shutdown after 6h without posts, resume after 1 week."""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

from core.account_info_store import load_account_info
from core.account_logging import account_log
from core.account_shutdown import (
    NO_POST_THRESHOLD_SECONDS,
    account_expected_to_post,
    clear_shutdown,
    evaluate_posting_idle,
    get_shutdown_info,
    is_shutdown_active,
    put_on_shutdown_list,
    purge_expired,
    seconds_until_resume,
)
from core.config import ACCOUNTS
from core.system_lifecycle import log_system_event

if TYPE_CHECKING:
    from services.account_manager import AccountManager

CHECK_INTERVAL_SECONDS = int(os.environ.get("ACCOUNT_SHUTDOWN_CHECK_SECONDS", "300"))


class AccountShutdownMonitor:
    def __init__(self, manager: "AccountManager") -> None:
        self._manager = manager
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                await self.check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_system_event(
                    "AccountShutdownMonitor error",
                    reason="shutdown_monitor",
                    detail=str(e)[:160],
                )

    async def check_all(self) -> None:
        now = time.time()
        for cleared in purge_expired():
            await self._resume_after_shutdown(cleared)
        for slot in ACCOUNTS:
            try:
                await self._check_slot(slot, now=now)
            except Exception as e:
                account_log(slot, f"Shutdown monitor error: {e}", level="warning")

    async def _check_slot(self, slot: str, *, now: float) -> None:
        if is_shutdown_active(slot):
            info = get_shutdown_info(slot)
            if info and now >= float(info.get("resume_at") or 0):
                clear_shutdown(slot)
                await self._resume_after_shutdown(slot, info=info)
                return
            w = self._manager.get_worker(slot)
            if w.state.running:
                account_log(
                    slot,
                    f"Shutdown list — stopping until "
                    f"{seconds_until_resume(slot) // 3600}h left",
                    level="warning",
                )
                await self._manager.stop_account(slot)
            return

        w = self._manager.get_worker(slot)
        st = w.state
        info = st.account_info or load_account_info(slot)
        if not info or not info.get("phone"):
            return

        if not account_expected_to_post(slot, st):
            return

        should_shutdown, reason, _idle, last_post = evaluate_posting_idle(slot, st, now=now)
        if not should_shutdown:
            return

        was_running = bool(st.running or account_expected_to_post(slot, st))
        await self._enter_shutdown(
            slot,
            reason=reason,
            was_running=was_running,
            last_send_at=last_post,
        )

    async def _enter_shutdown(
        self,
        slot: str,
        *,
        reason: str,
        was_running: bool,
        last_send_at: float | None,
    ) -> None:
        put_on_shutdown_list(
            slot,
            reason=reason,
            was_running=was_running,
            last_send_at=last_send_at,
        )
        hours = NO_POST_THRESHOLD_SECONDS // 3600
        days = 7
        msg = (
            f"Auto-shutdown: no successful posts for {hours}h+ — "
            f"resting {days} days before auto-restart"
        )
        log_system_event("Account auto-shutdown", reason="shutdown_monitor", detail=f"{slot}: {reason}")
        account_log(slot, msg, level="warning")
        w = self._manager.get_worker(slot)
        if w.state.running:
            await self._manager.stop_account(slot)
        from core.worker_persistence import mark_stopped

        mark_stopped(slot)
        if self._manager._on_change:
            await self._manager._on_change()

    async def _resume_after_shutdown(
        self,
        slot: str,
        *,
        info: dict | None = None,
    ) -> None:
        info = info or {}
        was_running = bool(info.get("was_running", True))
        account_log(slot, "Shutdown period ended — eligible for restart", level="info")
        log_system_event(
            "Account shutdown expired",
            reason="shutdown_monitor",
            detail=slot,
        )
        if not was_running:
            return
        info_obj = load_account_info(slot)
        if not info_obj or not info_obj.get("phone"):
            return
        w = self._manager.get_worker(slot)
        if w.state.running or is_shutdown_active(slot):
            return
        ok = await self._manager.start_account(slot, skip_refresh=True)
        if ok:
            account_log(slot, "Auto-restarted after shutdown week", level="info")
            if self._manager._on_change:
                await self._manager._on_change()
