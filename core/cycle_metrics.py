"""Per-account cycle execution metrics — duration, throughput, success ratio."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core.config import STATE_DIR


@dataclass
class CycleRunMetrics:
    account_id: str
    cycle_number: int = 0
    started_at: float = 0.0
    ended_at: float = 0.0
    duration_seconds: float = 0.0
    groups_total: int = 0
    groups_processed: int = 0
    groups_per_second: float = 0.0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    success_rate: float = 0.0
    ended_early: bool = False
    end_reason: str = "complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "cycle_number": self.cycle_number,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "groups_total": self.groups_total,
            "groups_processed": self.groups_processed,
            "groups_per_second": round(self.groups_per_second, 4),
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": round(self.success_rate, 2),
            "ended_early": self.ended_early,
            "end_reason": self.end_reason,
        }


@dataclass
class CycleMetricsStore:
    """Latest + rolling history per account (in-memory, last run persisted)."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _latest: dict[str, CycleRunMetrics] = field(default_factory=dict)
    _history: dict[str, list[dict]] = field(default_factory=dict)
    _history_max: int = 20

    def start_cycle(self, account_id: str, cycle_number: int, groups_total: int) -> CycleRunMetrics:
        m = CycleRunMetrics(
            account_id=account_id,
            cycle_number=cycle_number,
            started_at=time.time(),
            groups_total=groups_total,
        )
        with self._lock:
            self._latest[account_id] = m
        return m

    def finish_cycle(
        self,
        account_id: str,
        *,
        success: int,
        failed: int,
        skipped: int,
        groups_processed: int,
        ended_early: bool = False,
        end_reason: str = "complete",
    ) -> CycleRunMetrics | None:
        with self._lock:
            m = self._latest.get(account_id)
            if m is None:
                return None
            m.ended_at = time.time()
            m.duration_seconds = max(0.0, m.ended_at - m.started_at)
            m.success = success
            m.failed = failed
            m.skipped = skipped
            m.groups_processed = groups_processed
            m.ended_early = ended_early
            m.end_reason = end_reason
            total = success + failed
            m.success_rate = round(success / total * 100, 2) if total > 0 else 0.0
            if m.duration_seconds > 0 and groups_processed > 0:
                m.groups_per_second = groups_processed / m.duration_seconds
            snap = m.to_dict()
            hist = self._history.setdefault(account_id, [])
            hist.append(snap)
            if len(hist) > self._history_max:
                del hist[: len(hist) - self._history_max]
        self._persist_last(account_id, snap)
        return m

    def latest(self, account_id: str) -> dict[str, Any] | None:
        with self._lock:
            m = self._latest.get(account_id)
            return m.to_dict() if m else None

    def history(self, account_id: str, limit: int = 10) -> list[dict]:
        with self._lock:
            return list(self._history.get(account_id, [])[-limit:])

    def scope(self, account_id: str) -> "AccountCycleMetrics":
        return AccountCycleMetrics(self, account_id)

    def _persist_last(self, account_id: str, data: dict) -> None:
        path = os.path.join(STATE_DIR, account_id, "cycle_metrics_last.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except OSError:
            pass


cycle_metrics_store = CycleMetricsStore()


class AccountCycleMetrics:
    """Account-scoped facade over the shared in-process metrics store."""

    def __init__(self, store: CycleMetricsStore, account_id: str) -> None:
        self._store = store
        self.account_id = account_id

    def start_cycle(self, cycle_number: int, groups_total: int) -> CycleRunMetrics:
        return self._store.start_cycle(self.account_id, cycle_number, groups_total)

    def finish_cycle(
        self,
        *,
        success: int,
        failed: int,
        skipped: int,
        groups_processed: int,
        ended_early: bool = False,
        end_reason: str = "complete",
    ) -> CycleRunMetrics | None:
        return self._store.finish_cycle(
            self.account_id,
            success=success,
            failed=failed,
            skipped=skipped,
            groups_processed=groups_processed,
            ended_early=ended_early,
            end_reason=end_reason,
        )

    def latest(self) -> dict[str, Any] | None:
        return self._store.latest(self.account_id)

    def history(self, limit: int = 10) -> list[dict]:
        return self._store.history(self.account_id, limit=limit)
