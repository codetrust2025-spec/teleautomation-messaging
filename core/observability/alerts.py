"""Per-account alert ring buffer for dashboard / ops."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

_MAX_ALERTS_PER_ACCOUNT = 50


class AlertStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._alerts: dict[str, deque] = {}

    def push(
        self,
        account_id: str,
        level: str,
        message: str,
        *,
        code: str = "general",
        extra: dict | None = None,
    ) -> dict[str, Any]:
        entry = {
            "account_id": account_id,
            "level": level,
            "code": code,
            "message": message[:500],
            "ts": time.time(),
            "extra": extra or {},
        }
        with self._lock:
            ring = self._alerts.setdefault(account_id, deque(maxlen=_MAX_ALERTS_PER_ACCOUNT))
            ring.append(entry)
        return entry

    def recent(self, account_id: str | None = None, limit: int = 20) -> list[dict]:
        with self._lock:
            if account_id:
                return list(self._alerts.get(account_id, []))[-limit:]
            out: list[dict] = []
            for ring in self._alerts.values():
                out.extend(list(ring)[-limit:])
            out.sort(key=lambda x: x["ts"], reverse=True)
            return out[:limit]

    def for_account(self, account_id: str) -> list[dict]:
        with self._lock:
            return list(self._alerts.get(account_id, []))


alert_store = AlertStore()
