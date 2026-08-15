"""
Worker watchdog — 24/7 health monitor for account workers.

If a worker is marked running but its task died or is stuck, restart it automatically.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from core import telegram_client
from core.config import ACCOUNTS
from core.system_lifecycle import log_system_event

if TYPE_CHECKING:
    from services.account_manager import AccountManager

# Running but no cycle progress for this long → restart task (not account sleep)
WORKER_STALE_SECONDS = int(__import__("os").environ.get("WORKER_STALE_SECONDS", "2700"))  # 45 min
WATCHDOG_INTERVAL_SECONDS = int(__import__("os").environ.get("WATCHDOG_INTERVAL_SECONDS", "45"))


class WorkerWatchdog:
    def __init__(self, registry: "AccountManager"):
        self._registry = registry
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
                await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
                await self._check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_system_event("Watchdog loop error", reason="watchdog", detail=str(e)[:120])

    async def _check_all(self) -> None:
        now = time.time()
        for slot in ACCOUNTS:
            w = self._registry.get_worker(slot)
            st = w.state
            if not st.running:
                continue
            if telegram_client.is_login_exclusive(slot):
                continue

            task = st.task
            # Running flag set but no live task → restart
            if task is None or task.done():
                if not st.account_info:
                    continue
                log_system_event(
                    "Worker task missing — auto-restarting",
                    reason="watchdog",
                    detail=slot,
                )
                try:
                    if telegram_client.is_login_exclusive(slot):
                        continue
                    from core.worker_persistence import mark_running

                    mark_running(slot)
                    w._launch_task()
                except Exception as e:
                    log_system_event("Watchdog restart failed", reason="watchdog", detail=f"{slot}: {e}")
                continue

            last = getattr(st, "last_activity_at", 0.0) or 0.0
            # Skip stale check during long flood sleep (next_cycle_in can be hours)
            if st.heavy_rate_limit or st.status == "flood_wait":
                continue
            if last > 0 and (now - last) > WORKER_STALE_SECONDS:
                log_system_event(
                    "Worker appears stuck — restarting task",
                    reason="watchdog",
                    detail=f"{slot} idle {int(now - last)}s",
                )
                try:
                    w._cancel_task()
                    await asyncio.sleep(0.3)
                    if st.running:
                        w._launch_task()
                except Exception as e:
                    log_system_event("Watchdog unstuck failed", reason="watchdog", detail=f"{slot}: {e}")
