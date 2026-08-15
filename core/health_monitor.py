"""
HealthMonitor — per-account self-healing checks (stuck worker, dead processor, queue overflow).

Runs in one asyncio loop; actions are scoped to a single account_id only.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from core import telegram_client
from core.account_logging import account_log
from core.config import ACCOUNTS
from core.observability.account_metrics import metrics_store
from core.observability.alerts import alert_store
from core.system_lifecycle import log_system_event
from events.event_bus import event_bus
from events.event_types import EventType
from messaging.queue_config import (
    AUTO_RESTART_ON_CRASH,
    HEALTH_CHECK_INTERVAL,
    MAX_QUEUE_SIZE,
    PROCESSOR_STALE_SECONDS,
    QUEUE_HIGH_WATERMARK,
    WORKER_STALE_SECONDS,
)

if TYPE_CHECKING:
    from services.account_manager import AccountManager


class HealthMonitor:
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
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                await self.check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_system_event("HealthMonitor loop error", reason="watchdog", detail=str(e)[:120])

    async def check_all(self) -> None:
        now = time.time()
        for slot in ACCOUNTS:
            try:
                await self.check_account(slot, now=now)
            except Exception as e:
                account_log(slot, f"Health check error: {e}", level="warning")

    async def check_account(self, slot: str, *, now: float | None = None) -> list[str]:
        now = now or time.time()
        issues: list[str] = []
        w = self._manager.get_worker(slot)
        st = w.state
        q = self._manager.get_runtime(slot).queue

        if not st.running:
            return issues

        if telegram_client.is_login_exclusive(slot):
            return issues

        # Queue overflow / high watermark
        if q.depth >= MAX_QUEUE_SIZE:
            issues.append("queue_full")
            alert_store.push(slot, "error", f"Queue full {q.depth}/{MAX_QUEUE_SIZE}", code="queue_full")
            await event_bus.publish(
                EventType.QUEUE_OVERFLOW,
                slot,
                {"depth": q.depth, "max_size": MAX_QUEUE_SIZE},
                push_state=True,
            )
        elif q.high_watermark:
            issues.append("queue_high_water")
            await event_bus.publish(
                EventType.HEALTH_ALERT,
                slot,
                {"message": "Queue high watermark", "depth": q.depth},
                push_state=False,
            )

        # Dead posting task
        task = st.task
        if task is None or task.done():
            if st.account_info:
                issues.append("worker_task_dead")
                await self._restart_worker(slot, reason="worker_task_dead")

        # Stuck posting loop (no activity)
        elif not (st.heavy_rate_limit or st.status == "flood_wait"):
            last = getattr(st, "last_activity_at", 0.0) or 0.0
            if last > 0 and (now - last) > WORKER_STALE_SECONDS:
                issues.append("worker_stale")
                await self._restart_worker(slot, reason=f"stale_{int(now - last)}s")

        # Dead queue processor
        qtask = w._queue_task
        if st.running and (qtask is None or qtask.done()):
            issues.append("processor_dead")
            account_log(slot, "Queue processor dead — restarting", level="warning")
            await w.ensure_queue_processor()

        # Processor not dequeuing while queue deep
        elif q.depth > 5 and (now - q._last_dequeue_at) > PROCESSOR_STALE_SECONDS:
            issues.append("processor_stale")
            alert_store.push(slot, "warning", "Queue processor stale", code="processor_stale")
            await w.stop_queue_processor()
            await asyncio.sleep(0.2)
            await w.ensure_queue_processor()

        return issues

    async def _restart_worker(self, slot: str, *, reason: str) -> None:
        log_system_event("HealthMonitor restart", reason="watchdog", detail=f"{slot}: {reason}")
        alert_store.push(slot, "warning", f"Restarting worker: {reason}", code="worker_restart")
        metrics_store.record_worker_restart(slot)
        await event_bus.publish(
            EventType.HEALTH_ALERT,
            slot,
            {"message": f"Restarting worker: {reason}"},
            push_state=False,
        )
        if AUTO_RESTART_ON_CRASH:
            ok = await self._manager.get_runtime(slot).restart()
            if ok:
                await event_bus.publish(
                    EventType.WORKER_RESTARTED,
                    slot,
                    {"reason": reason},
                    push_state=True,
                )
