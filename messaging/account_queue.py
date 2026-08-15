"""Per-account priority queues — strictly isolated, no shared queue."""

from __future__ import annotations

import asyncio
import heapq
import time
from dataclasses import dataclass, field
from typing import Any

from core.account_logging import account_log
from core.config import ACCOUNTS
from core.observability.alerts import alert_store
from messaging.queue_config import (
    MAX_QUEUE_SIZE,
    QUEUE_BACKPRESSURE_POLICY,
    QUEUE_HIGH_WATERMARK,
    QUEUE_PUT_TIMEOUT,
)
from messaging.task_types import QueueTask, TaskPriority, TaskType


class QueueBackpressureError(Exception):
    """Raised when per-account queue is full and put timeout elapsed."""

    def __init__(self, account_id: str, depth: int, max_size: int):
        self.account_id = account_id
        self.depth = depth
        self.max_size = max_size
        super().__init__(f"[{account_id}] Queue full ({depth}/{max_size})")


@dataclass(order=True)
class _HeapEntry:
    priority: int
    sequence: int
    task: QueueTask = field(compare=False)


class AccountQueue:
    """Dedicated priority queue for a single account slot."""

    def __init__(self, account_id: str, *, max_size: int = MAX_QUEUE_SIZE) -> None:
        if account_id not in ACCOUNTS:
            raise ValueError(f"Invalid account_id: {account_id}")
        self.account_id = account_id
        self.max_size = max_size
        self._heap: list[_HeapEntry] = []
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()
        self._pending: dict[str, asyncio.Future] = {}
        self._processing = False
        self._last_dequeue_at: float = time.time()
        self._rejected_total = 0
        self._dropped_total = 0
        self._overflow_alerted = False

    @property
    def depth(self) -> int:
        return len(self._heap)

    @property
    def is_processing(self) -> bool:
        return self._processing

    @property
    def high_watermark(self) -> bool:
        return self.depth >= int(self.max_size * QUEUE_HIGH_WATERMARK)

    def status_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "depth": self.depth,
            "max_size": self.max_size,
            "processing": self._processing,
            "high_watermark": self.high_watermark,
            "rejected_total": self._rejected_total,
            "dropped_total": self._dropped_total,
            "backpressure_policy": QUEUE_BACKPRESSURE_POLICY,
            "last_dequeue_at": self._last_dequeue_at,
        }

    def _drop_lowest_priority_task(self) -> bool:
        """Evict one lowest-priority pending task (same account only)."""
        if not self._heap:
            return False
        worst = max(self._heap, key=lambda e: e.priority)
        if worst.priority <= int(TaskPriority.HIGH.value):
            return False
        self._heap.remove(worst)
        heapq.heapify(self._heap)
        self._dropped_total += 1
        account_log(
            self.account_id,
            f"Dropped low-priority task {worst.task.task_type.value} (backpressure)",
            level="warning",
        )
        return True

    def _enqueue_unlocked(self, task: QueueTask) -> None:
        self._sequence += 1
        entry = _HeapEntry(
            priority=int(task.priority.value),
            sequence=self._sequence,
            task=task,
        )
        heapq.heappush(self._heap, entry)
        self._not_empty.set()
        if self.high_watermark and not self._overflow_alerted:
            self._overflow_alerted = True
            alert_store.push(
                self.account_id,
                "warning",
                f"Queue high watermark ({self.depth}/{self.max_size})",
                code="queue_high_water",
            )
        elif not self.high_watermark:
            self._overflow_alerted = False
        account_log(
            self.account_id,
            f"Queued {task.task_type.value} prio={task.priority.name} depth={self.depth}",
            level="debug",
        )

    async def put(self, task: QueueTask, *, timeout: float | None = None) -> None:
        if task.account_id != self.account_id:
            raise ValueError(
                f"Task account {task.account_id} does not match queue {self.account_id}"
            )
        if task.wait_result:
            loop = asyncio.get_running_loop()
            self._pending[task.task_id] = loop.create_future()

        policy = QUEUE_BACKPRESSURE_POLICY
        if policy == "reject":
            async with self._lock:
                if len(self._heap) >= self.max_size:
                    self._rejected_total += 1
                    raise QueueBackpressureError(self.account_id, self.depth, self.max_size)
                self._enqueue_unlocked(task)
            return

        deadline = time.time() + (timeout if timeout is not None else QUEUE_PUT_TIMEOUT)
        while True:
            async with self._lock:
                if len(self._heap) < self.max_size:
                    self._enqueue_unlocked(task)
                    return
                if policy == "drop_low" and self._drop_lowest_priority_task():
                    self._enqueue_unlocked(task)
                    return
            if policy == "reject":
                self._rejected_total += 1
                raise QueueBackpressureError(self.account_id, self.depth, self.max_size)
            if time.time() >= deadline:
                self._rejected_total += 1
                if task.wait_result:
                    fut = self._pending.pop(task.task_id, None)
                    if fut and not fut.done():
                        fut.set_exception(
                            QueueBackpressureError(self.account_id, self.depth, self.max_size)
                        )
                raise QueueBackpressureError(self.account_id, self.depth, self.max_size)
            await asyncio.sleep(0.25)

    def count_priority_at_most(self, max_priority: int) -> int:
        """Count pending tasks at or above priority (lower int = higher priority)."""
        return sum(1 for e in self._heap if e.priority <= max_priority)

    async def pop_highest_priority(self) -> QueueTask | None:
        """Remove and return the highest-priority pending task, if any."""
        async with self._lock:
            if not self._heap:
                return None
            best = min(self._heap, key=lambda e: (e.priority, e.sequence))
            self._heap.remove(best)
            heapq.heapify(self._heap)
            if not self._heap:
                self._not_empty.clear()
            self._last_dequeue_at = time.time()
            return best.task

    async def get(self, timeout: float | None = None) -> QueueTask | None:
        while True:
            async with self._lock:
                if self._heap:
                    entry = heapq.heappop(self._heap)
                    if not self._heap:
                        self._not_empty.clear()
                    self._last_dequeue_at = time.time()
                    return entry.task
            try:
                if timeout is None:
                    await self._not_empty.wait()
                else:
                    await asyncio.wait_for(self._not_empty.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return None

    def task_done(self) -> None:
        pass

    def set_processing(self, active: bool) -> None:
        self._processing = active

    def complete_task(self, task_id: str, result: Any = None, error: Exception | None = None) -> None:
        fut = self._pending.pop(task_id, None)
        if fut is None or fut.done():
            return
        if error is not None:
            fut.set_exception(error)
        else:
            fut.set_result(result)

    async def wait_for_task(self, task: QueueTask, timeout: float = 300.0) -> Any:
        fut = self._pending.get(task.task_id)
        if fut is None:
            raise RuntimeError(f"No wait future for task {task.task_id}")
        return await asyncio.wait_for(fut, timeout=timeout)

    async def drain(self) -> int:
        async with self._lock:
            n = len(self._heap)
            self._heap.clear()
            self._not_empty.clear()
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        return n

    async def has_pending_ai_auto_reply_for_user(self, user_id: int) -> bool:
        uid = int(user_id)
        async with self._lock:
            return any(
                entry.task.task_type == TaskType.AI_AUTO_REPLY
                and int((entry.task.payload or {}).get("user_id") or 0) == uid
                for entry in self._heap
            )

    async def cancel_ai_auto_reply_for_user(self, user_id: int) -> int:
        """Drop pending AI auto-replies for one chat (e.g. operator sent manually)."""
        uid = int(user_id)
        async with self._lock:
            kept: list[_HeapEntry] = []
            removed = 0
            for entry in self._heap:
                task = entry.task
                if (
                    task.task_type == TaskType.AI_AUTO_REPLY
                    and int((task.payload or {}).get("user_id") or 0) == uid
                ):
                    removed += 1
                    fut = self._pending.pop(task.task_id, None)
                    if fut and not fut.done():
                        fut.set_result({"ok": False, "reason": "cancelled"})
                else:
                    kept.append(entry)
            if removed:
                self._heap = kept
                heapq.heapify(self._heap)
                if not self._heap:
                    self._not_empty.clear()
                account_log(
                    self.account_id,
                    f"Cancelled {removed} pending AI_AUTO_REPLY for user {uid}",
                    level="debug",
                )
            return removed


class AccountQueueManager:
    """Registry of per-account queues — no shared queue instance."""

    def __init__(self) -> None:
        self._queues: dict[str, AccountQueue] = {}

    def get_queue(self, account_id: str) -> AccountQueue:
        if account_id not in ACCOUNTS:
            raise ValueError(f"Invalid account_id: {account_id}")
        if account_id not in self._queues:
            self._queues[account_id] = AccountQueue(account_id)
        return self._queues[account_id]

    def all_status(self) -> dict[str, dict]:
        return {aid: self.get_queue(aid).status_dict() for aid in ACCOUNTS}

    async def drain_account(self, account_id: str) -> int:
        return await self.get_queue(account_id).drain()


queue_manager = AccountQueueManager()
