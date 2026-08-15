"""
Queue backend abstraction — today: in-process memory; tomorrow: Redis per account.

NON-NEGOTIABLE: Each account_id maps to its own logical queue namespace.
No cross-account list keys in Redis design.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import logging

from messaging.queue_config import QUEUE_BACKEND
from messaging.task_types import QueueTask, TaskPriority, TaskType

logger = logging.getLogger("queue_backend")


class QueueBackend(ABC):
    @abstractmethod
    async def enqueue(self, account_id: str, task: QueueTask) -> None: ...

    @abstractmethod
    async def dequeue(self, account_id: str, timeout: float = 1.0) -> QueueTask | None: ...

    @abstractmethod
    async def depth(self, account_id: str) -> int: ...


class InMemoryQueueBackend(QueueBackend):
    """Delegates to AccountQueueManager (current production path)."""

    async def enqueue(self, account_id: str, task: QueueTask) -> None:
        from messaging.account_queue import queue_manager

        await queue_manager.get_queue(account_id).put(task)

    async def dequeue(self, account_id: str, timeout: float = 1.0) -> QueueTask | None:
        from messaging.account_queue import queue_manager

        return await queue_manager.get_queue(account_id).get(timeout=timeout)

    async def depth(self, account_id: str) -> int:
        from messaging.account_queue import queue_manager

        return queue_manager.get_queue(account_id).depth


class RedisQueueBackend(QueueBackend):
    """
    Future: one Redis list/stream per account, e.g. tf:queue:{account_id}.
    Worker process(es) BRPOP per account — still no shared consumer across accounts.

    Not active until QUEUE_BACKEND=redis and REDIS_URL are set.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client = None

    async def _get_client(self):
        if self._client is None:
            raise NotImplementedError(
                "Redis queue backend not wired yet. Set QUEUE_BACKEND=memory. "
                "See docs/SCALABILITY.md for migration steps."
            )
        return self._client

    @staticmethod
    def _serialize(task: QueueTask) -> str:
        return json.dumps({
            "account_id": task.account_id,
            "task_type": task.task_type.value,
            "payload": task.payload,
            "task_id": task.task_id,
            "retry_count": task.retry_count,
            "wait_result": task.wait_result,
            "priority": task.priority.value,
        })

    @staticmethod
    def _deserialize(raw: str) -> QueueTask:
        d = json.loads(raw)
        return QueueTask(
            account_id=d["account_id"],
            task_type=TaskType(d["task_type"]),
            payload=d.get("payload") or {},
            task_id=d.get("task_id", ""),
            retry_count=int(d.get("retry_count") or 0),
            wait_result=bool(d.get("wait_result")),
            priority=TaskPriority(int(d.get("priority", TaskPriority.NORMAL.value))),
        )

    async def enqueue(self, account_id: str, task: QueueTask) -> None:
        await self._get_client()
        raise NotImplementedError

    async def dequeue(self, account_id: str, timeout: float = 1.0) -> QueueTask | None:
        await self._get_client()
        raise NotImplementedError

    async def depth(self, account_id: str) -> int:
        await self._get_client()
        raise NotImplementedError


def get_queue_backend() -> QueueBackend:
    if QUEUE_BACKEND == "redis":
        logger.error(
            "QUEUE_BACKEND=redis is not wired yet — falling back to in-memory queue. "
            "Set QUEUE_BACKEND=memory or implement the Redis backend (see docs/SCALABILITY.md)."
        )
        return InMemoryQueueBackend()
    return InMemoryQueueBackend()


queue_backend = get_queue_backend()
