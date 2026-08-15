"""
Fair scheduling — cycle progress guaranteed under heavy DM / retry load.
"""

from __future__ import annotations

import asyncio
import time

from messaging.task_types import TaskPriority, TaskType


class CycleFairScheduler:
    """
    Ensures each cycle processes a minimum number of groups before yielding to DMs.
    Bounds total yield time so cycles cannot stall indefinitely.
    """

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self._cycle_started_at = 0.0
        self._groups_since_yield = 0
        self._total_yield_ms = 0.0
        self._policy_min_groups = 3
        self._policy_max_yield_ms = 2000
        self._policy_max_wall_s = 5400

    def begin_cycle(self, policy) -> None:
        self._cycle_started_at = time.time()
        self._groups_since_yield = 0
        self._total_yield_ms = 0.0
        if policy is not None:
            self._policy_min_groups = policy.min_groups_before_dm_yield
            self._policy_max_yield_ms = policy.max_dm_yield_ms
            self._policy_max_wall_s = policy.max_cycle_wall_seconds

    def on_group_completed(self) -> None:
        self._groups_since_yield += 1

    def cycle_wall_exceeded(self) -> bool:
        if self._cycle_started_at <= 0:
            return False
        return (time.time() - self._cycle_started_at) >= self._policy_max_wall_s

    def should_yield_to_dms(self) -> bool:
        if self.cycle_wall_exceeded():
            return False
        if self._groups_since_yield < self._policy_min_groups:
            return False
        if self._total_yield_ms >= self._policy_max_yield_ms:
            return False
        queue = self._queue_for_account()
        return queue.count_priority_at_most(int(TaskPriority.HIGH.value)) > 0

    def _queue_for_account(self):
        from services.account_manager import manager

        return manager.get_runtime(self.account_id).queue

    async def yield_for_priority_work(self, worker) -> int:
        """
        Service up to 2 high-priority queue tasks inline so DMs progress
        without starving the cycle (bounded time budget).
        """
        if not self.should_yield_to_dms():
            await asyncio.sleep(0)
            return 0

        queue = self._queue_for_account()
        serviced = 0
        start = time.time()
        budget_left_ms = self._policy_max_yield_ms - self._total_yield_ms

        while serviced < 2 and budget_left_ms > 0:
            task = await queue.pop_highest_priority()
            if task is None:
                break
            if int(task.priority.value) > int(TaskPriority.HIGH.value):
                await queue.put(task)
                break
            if task.task_type in (TaskType.RUN_CYCLE,):
                await queue.put(task)
                break

            t0 = time.time()
            try:
                result = await worker._handle_queue_task(task)
                if task.wait_result:
                    queue.complete_task(task.task_id, result)
            except Exception as exc:
                if task.wait_result:
                    queue.complete_task(task.task_id, error=exc)
                from messaging.retry_manager import retry_manager

                await retry_manager.schedule_retry_from_exception(self.account_id, task, exc)
            else:
                from core.observability.account_metrics import metrics_store

                metrics_store.record_task_ok(self.account_id)

            serviced += 1
            elapsed_ms = (time.time() - t0) * 1000
            self._total_yield_ms += elapsed_ms
            budget_left_ms = self._policy_max_yield_ms - self._total_yield_ms
            if budget_left_ms <= 0:
                break

        if serviced > 0:
            self._groups_since_yield = 0

        await asyncio.sleep(0)
        return serviced
