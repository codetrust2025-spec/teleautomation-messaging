"""Per-account runtime capsule.

This is the single-process boundary for one account. The API/manager may
supervise many runtimes, but each runtime owns exactly one worker and queue.
The shape is intentionally close to a future process boundary: callers route
work through this object instead of reaching into global queue/worker state.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from core.account_info_store import load_account_info
from core.account_logging import account_log
from core.config import ACCOUNTS
from core.session_manager import session_manager
from core.worker_persistence import mark_running, mark_stopped
from core.observability.account_metrics import metrics_store
from events.event_bus import event_bus
from events.event_types import EventType
from messaging.account_queue import AccountQueue, queue_manager
from workers.account_worker import AccountWorker

OnChange = Callable[[], Awaitable[None]]


class AccountRuntime:
    """Owns all mutable runtime objects for one account."""

    def __init__(self, account_id: str, *, on_change: OnChange | None = None) -> None:
        if account_id not in ACCOUNTS:
            raise ValueError(f"Invalid account_id: {account_id}")
        self.account_id = account_id
        self.queue: AccountQueue = queue_manager.get_queue(account_id)
        self.worker = AccountWorker(account_id, on_state_change=on_change, queue=self.queue)
        self.worker.set_manager(self)
        self._lifecycle_lock = asyncio.Lock()

    def set_on_change(self, cb: OnChange | None) -> None:
        self.worker._on_state_change = cb

    @property
    def state(self):
        return self.worker.state

    async def start(
        self,
        *,
        one_shot: bool = False,
        skip_refresh: bool = False,
        campaign: bool | None = None,
        forwarding: bool | None = None,
    ) -> bool:
        async with self._lifecycle_lock:
            if not skip_refresh or not self.worker.state.account_info:
                await self.worker.refresh_info()
            if not self.worker.state.account_info:
                account_log(self.account_id, "Cannot start — not logged in", level="warning")
                return False
            await self.worker.ensure_queue_processor()
            if self.worker.start(
                one_shot=one_shot,
                campaign=campaign,
                forwarding=forwarding,
            ):
                mark_running(self.account_id)
                account_log(self.account_id, "Worker started", level="info")
                await event_bus.publish(
                    EventType.ACCOUNT_STATE,
                    self.account_id,
                    {"lifecycle": "RUNNING"},
                )
                return True
            return False

    async def stop(
        self,
        *,
        wait: float = 1.0,
        release_session: bool = True,
        campaign: bool | None = None,
        forwarding: bool | None = None,
    ) -> None:
        async with self._lifecycle_lock:
            await self._stop_unlocked(
                wait=wait,
                release_session=release_session,
                campaign=campaign,
                forwarding=forwarding,
            )

    async def _stop_unlocked(
        self,
        *,
        wait: float,
        release_session: bool,
        campaign: bool | None = None,
        forwarding: bool | None = None,
    ) -> None:
        self.worker.stop(campaign=campaign, forwarding=forwarding)
        mark_stopped(self.account_id)
        task = self.worker.state.task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=8.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
        if release_session:
            await session_manager.release(self.account_id, wait=wait)
        await event_bus.publish(
            EventType.ACCOUNT_STATE,
            self.account_id,
            {"lifecycle": "STOPPED"},
        )

    async def restart(self, *, one_shot: bool = False) -> bool:
        account_log(self.account_id, "Restarting isolated account runtime", level="info")
        async with self._lifecycle_lock:
            await self._stop_unlocked(wait=0.5, release_session=False)
            await asyncio.sleep(0)
            await self.worker.ensure_queue_processor()
            if self.worker.start(one_shot=one_shot):
                mark_running(self.account_id)
                await event_bus.publish(
                    EventType.ACCOUNT_STATE,
                    self.account_id,
                    {"lifecycle": "RUNNING"},
                )
                return True
            return False

    async def handle_worker_crash(self, account_id: str, exc: BaseException | None = None) -> None:
        if account_id != self.account_id:
            raise ValueError(f"Crash for {account_id} cannot be handled by {self.account_id}")
        account_log(
            self.account_id,
            f"Isolated worker crash — restarting this account only: {exc}",
            level="error",
        )
        metrics_store.record_worker_restart(self.account_id)
        if self.worker.state.running:
            await self.restart(one_shot=False)

    async def drain_queue(self) -> int:
        return await self.queue.drain()

    def has_login(self) -> bool:
        return bool(self.worker.state.account_info or load_account_info(self.account_id))
