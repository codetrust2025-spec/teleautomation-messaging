"""Per-account retry scheduling — exponential backoff, FloodWait, network errors."""

from __future__ import annotations

import asyncio
import random
import re
import time
from collections import deque
from typing import Any

from core.account_logging import account_log
from core.observability.account_metrics import metrics_store
from core.observability.alerts import alert_store
from events.event_bus import event_bus
from events.event_types import EventType
from messaging.message_router import message_router
from messaging.queue_config import (
    RETRY_BASE_SECONDS,
    RETRY_JITTER_RATIO,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_SECONDS,
    RETRY_STORM_MAX_PER_ACCOUNT,
    RETRY_STORM_WINDOW_SECONDS,
)
from messaging.task_types import QueueTask, TaskPriority, TaskType, priority_for_task_type

_FLOOD_RE = re.compile(r"flood|FloodWait|rate.?limit", re.I)
_NETWORK_RE = re.compile(
    r"disconnect|timeout|network|connection|database is locked|session",
    re.I,
)


class RetryClassification:
    __slots__ = ("flood_seconds", "network", "retryable", "reason")

    def __init__(
        self,
        *,
        flood_seconds: int = 0,
        network: bool = False,
        retryable: bool = True,
        reason: str = "error",
    ) -> None:
        self.flood_seconds = flood_seconds
        self.network = network
        self.retryable = retryable
        self.reason = reason


def classify_exception(exc: BaseException) -> RetryClassification:
    text = str(exc)
    flood_seconds = 0

    if hasattr(exc, "seconds"):
        try:
            flood_seconds = int(getattr(exc, "seconds", 0) or 0)
        except (TypeError, ValueError):
            flood_seconds = 0

    if flood_seconds > 0 or _FLOOD_RE.search(text):
        if flood_seconds <= 0:
            m = re.search(r"(\d+)\s*s", text)
            flood_seconds = int(m.group(1)) if m else 60
        return RetryClassification(
            flood_seconds=flood_seconds,
            retryable=True,
            reason="flood_wait",
        )

    if _NETWORK_RE.search(text):
        return RetryClassification(network=True, retryable=True, reason="network")

    if "invalid" in text.lower() or "not logged in" in text.lower():
        return RetryClassification(retryable=False, reason="fatal")

    return RetryClassification(retryable=True, reason="error")


def classify_task_result(result: Any) -> RetryClassification | None:
    """Optional retry hint from group post result codes."""
    if result == "flood":
        return RetryClassification(flood_seconds=60, reason="flood_result")
    if result in ("error", "session_break"):
        return RetryClassification(network=True, reason="session")
    return None


class RetryManager:
    """Schedules retries into the owning account's queue only."""

    def __init__(self) -> None:
        self._scheduled: dict[str, set[str]] = {}
        self._retry_times: dict[str, deque] = {}

    def _prune_storm_windows(self, now: float) -> None:
        cutoff = now - RETRY_STORM_WINDOW_SECONDS
        for aid, dq in list(self._retry_times.items()):
            while dq and dq[0] < cutoff:
                dq.popleft()
            if not dq:
                self._retry_times.pop(aid, None)

    def _retry_storm_ok(self, account_id: str) -> bool:
        now = time.time()
        self._prune_storm_windows(now)
        per = self._retry_times.get(account_id, deque())
        if len(per) >= RETRY_STORM_MAX_PER_ACCOUNT:
            return False
        return True

    def _record_retry_scheduled(self, account_id: str) -> None:
        now = time.time()
        dq = self._retry_times.setdefault(account_id, deque())
        dq.append(now)

    def _track(self, account_id: str, task_id: str) -> bool:
        seen = self._scheduled.setdefault(account_id, set())
        if task_id in seen:
            return False
        seen.add(task_id)
        return True

    def _untrack(self, account_id: str, task_id: str) -> None:
        self._scheduled.get(account_id, set()).discard(task_id)

    def compute_delay(
        self,
        *,
        flood_seconds: int = 0,
        network: bool = False,
        retry_count: int = 0,
    ) -> float:
        if flood_seconds > 0:
            base = min(float(flood_seconds), RETRY_MAX_SECONDS)
        elif network:
            base = min(RETRY_BASE_SECONDS * (2**retry_count), RETRY_MAX_SECONDS)
        else:
            base = min(RETRY_BASE_SECONDS * (1.8**retry_count), 600.0)

        jitter = base * RETRY_JITTER_RATIO * (random.random() * 2 - 1)
        return max(1.0, min(base + jitter, RETRY_MAX_SECONDS))

    async def schedule_retry(
        self,
        account_id: str,
        original: QueueTask,
        *,
        reason: str,
        flood_seconds: int = 0,
        network: bool = False,
        classification: RetryClassification | None = None,
    ) -> bool:
        clf = classification or RetryClassification(
            flood_seconds=flood_seconds,
            network=network,
            reason=reason,
        )
        if not clf.retryable:
            metrics_store.record_retry_exhausted(account_id)
            alert_store.push(account_id, "error", f"Not retryable: {clf.reason}", code="retry_skip")
            return False

        if original.retry_count >= RETRY_MAX_ATTEMPTS:
            metrics_store.record_retry_exhausted(account_id)
            account_log(account_id, f"Max retries reached for {original.task_type.value}", level="warning")
            alert_store.push(
                account_id,
                "error",
                f"Retries exhausted for {original.task_type.value}",
                code="retry_exhausted",
            )
            await event_bus.publish(
                EventType.RETRY_EXHAUSTED,
                account_id,
                {"reason": clf.reason, "task": original.to_dict()},
                push_state=False,
            )
            return False

        if not self._retry_storm_ok(account_id):
            account_log(
                account_id,
                f"Retry storm cap — deferring {original.task_type.value}",
                level="warning",
            )
            alert_store.push(
                account_id,
                "warning",
                "Retry storm protection active",
                code="retry_storm",
            )
            delay = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** (original.retry_count + 2)))
            clf = RetryClassification(
                flood_seconds=int(delay),
                network=True,
                reason="retry_storm_backoff",
            )

        if not self._track(account_id, original.task_id):
            return False

        delay = self.compute_delay(
            flood_seconds=clf.flood_seconds,
            network=clf.network,
            retry_count=original.retry_count,
        )
        self._record_retry_scheduled(account_id)
        metrics_store.record_retry_scheduled(account_id)
        if clf.flood_seconds > 0:
            metrics_store.record_flood_wait(account_id)

        account_log(
            account_id,
            f"Retry {original.task_type.value} in {delay:.0f}s ({clf.reason})",
            level="warning",
        )
        alert_store.push(
            account_id,
            "warning",
            f"Retry in {delay:.0f}s: {clf.reason}",
            code="retry_scheduled",
            extra={"task_type": original.task_type.value, "attempt": original.retry_count + 1},
        )

        async def _enqueue() -> None:
            await asyncio.sleep(delay)
            self._untrack(account_id, original.task_id)
            orig_type = original.task_type
            if orig_type == TaskType.RETRY:
                orig_type = TaskType(original.payload.get("original_type", TaskType.GROUP_POST.value))
            retry_task = QueueTask(
                account_id=account_id,
                task_type=TaskType.RETRY,
                payload={
                    "original_type": orig_type.value,
                    "original_payload": dict(original.payload),
                },
                retry_count=original.retry_count + 1,
                wait_result=original.wait_result,
                priority=TaskPriority.RETRY,
            )
            retry_task.priority = priority_for_task_type(TaskType.RETRY, is_retry=True)
            try:
                await message_router.route(retry_task)
                await event_bus.publish(
                    EventType.RETRY_SCHEDULED,
                    account_id,
                    {"delay": delay, "task": retry_task.to_dict()},
                    push_state=False,
                )
            except Exception as e:
                account_log(account_id, f"Retry enqueue failed: {e}", level="error")

        asyncio.create_task(_enqueue())
        return True

    async def schedule_retry_from_exception(
        self,
        account_id: str,
        original: QueueTask,
        exc: BaseException,
    ) -> bool:
        clf = classify_exception(exc)
        return await self.schedule_retry(
            account_id,
            original,
            reason=clf.reason,
            flood_seconds=clf.flood_seconds,
            network=clf.network,
            classification=clf,
        )


retry_manager = RetryManager()
