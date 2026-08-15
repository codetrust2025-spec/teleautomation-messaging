"""Per-account logging — no global log mutation."""

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from core.structured_logging import LogEvent, build_log_entry

LogCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class AccountLogger:
    """Isolated log buffer for one account."""

    slot: str
    logs: list = field(default_factory=list)
    _on_log: LogCallback | None = None

    def set_callback(self, cb: LogCallback) -> None:
        self._on_log = cb

    async def log_event(
        self,
        event: LogEvent | str,
        level: str = "info",
        *,
        cycle: int | None = None,
        group: str | None = None,
        **fields: Any,
    ) -> None:
        entry = build_log_entry(
            account_id=self.slot,
            event=event,
            level=level,
            cycle=cycle,
            group_id=group,
            fields=fields or None,
        )
        await self._emit(entry)

    async def log(self, msg: str, level: str = "info") -> None:
        """Legacy free-text path — stored as GENERIC detail."""
        entry = build_log_entry(
            account_id=self.slot,
            event=LogEvent.GENERIC,
            level=level,
            fields={"detail": msg.strip()},
            message=msg,
        )
        await self._emit(entry)

    async def _emit(self, entry: dict[str, Any]) -> None:
        if self._on_log:
            await self._on_log(entry)
            return
        self.logs.append(entry)
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]
