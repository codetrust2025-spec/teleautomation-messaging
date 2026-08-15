"""Per-account metrics — isolated counters, no cross-account aggregation at write time."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AccountMetrics:
    account_id: str
    messages_sent: int = 0
    messages_failed: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    retries_scheduled: int = 0
    retries_exhausted: int = 0
    flood_waits: int = 0
    worker_restarts: int = 0
    queue_rejected: int = 0
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "messages_sent": self.messages_sent,
            "messages_failed": self.messages_failed,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "retries_scheduled": self.retries_scheduled,
            "retries_exhausted": self.retries_exhausted,
            "flood_waits": self.flood_waits,
            "worker_restarts": self.worker_restarts,
            "queue_rejected": self.queue_rejected,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "last_error": self.last_error[:200],
        }


class MetricsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_account: dict[str, AccountMetrics] = {}

    def _get(self, account_id: str) -> AccountMetrics:
        if account_id not in self._by_account:
            self._by_account[account_id] = AccountMetrics(account_id=account_id)
        return self._by_account[account_id]

    def record_sent(self, account_id: str) -> None:
        with self._lock:
            m = self._get(account_id)
            m.messages_sent += 1
            m.tasks_completed += 1
            m.last_success_at = time.time()

    def record_failed(self, account_id: str, *, error: str = "") -> None:
        with self._lock:
            m = self._get(account_id)
            m.messages_failed += 1
            m.tasks_failed += 1
            m.last_failure_at = time.time()
            if error:
                m.last_error = error

    def record_task_ok(self, account_id: str) -> None:
        with self._lock:
            m = self._get(account_id)
            m.tasks_completed += 1
            m.last_success_at = time.time()

    def record_task_fail(self, account_id: str, *, error: str = "") -> None:
        with self._lock:
            m = self._get(account_id)
            m.tasks_failed += 1
            m.last_failure_at = time.time()
            if error:
                m.last_error = error

    def record_retry_scheduled(self, account_id: str) -> None:
        with self._lock:
            self._get(account_id).retries_scheduled += 1

    def record_retry_exhausted(self, account_id: str) -> None:
        with self._lock:
            self._get(account_id).retries_exhausted += 1

    def record_flood_wait(self, account_id: str) -> None:
        with self._lock:
            self._get(account_id).flood_waits += 1

    def record_worker_restart(self, account_id: str) -> None:
        with self._lock:
            self._get(account_id).worker_restarts += 1

    def record_queue_rejected(self, account_id: str) -> None:
        with self._lock:
            self._get(account_id).queue_rejected += 1

    def snapshot(self, account_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if account_id:
                return self._get(account_id).to_dict()
            return {aid: m.to_dict() for aid, m in self._by_account.items()}

    def all_snapshots(self) -> dict[str, dict]:
        with self._lock:
            return {aid: m.to_dict() for aid, m in self._by_account.items()}

    def scope(self, account_id: str) -> "AccountMetricsScope":
        return AccountMetricsScope(self, account_id)


metrics_store = MetricsStore()


class AccountMetricsScope:
    """Account-scoped metrics facade for runtime-owned code paths."""

    def __init__(self, store: MetricsStore, account_id: str) -> None:
        self._store = store
        self.account_id = account_id

    def record_sent(self) -> None:
        self._store.record_sent(self.account_id)

    def record_failed(self, *, error: str = "") -> None:
        self._store.record_failed(self.account_id, error=error)

    def record_task_ok(self) -> None:
        self._store.record_task_ok(self.account_id)

    def record_task_fail(self, *, error: str = "") -> None:
        self._store.record_task_fail(self.account_id, error=error)

    def record_retry_scheduled(self) -> None:
        self._store.record_retry_scheduled(self.account_id)

    def record_retry_exhausted(self) -> None:
        self._store.record_retry_exhausted(self.account_id)

    def record_flood_wait(self) -> None:
        self._store.record_flood_wait(self.account_id)

    def record_worker_restart(self) -> None:
        self._store.record_worker_restart(self.account_id)

    def record_queue_rejected(self) -> None:
        self._store.record_queue_rejected(self.account_id)

    def snapshot(self) -> dict[str, Any]:
        return self._store.snapshot(self.account_id)
