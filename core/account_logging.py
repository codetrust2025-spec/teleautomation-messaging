"""Structured per-account logging — every line uses a consistent event schema."""

from __future__ import annotations

from typing import Any

from core.structured_logging import LogEvent, LogLevel, account_log_line, build_log_entry


def format_account_log(account_id: str, message: str) -> str:
    """Legacy helper — prefer account_log()."""
    return build_log_entry(
        account_id=account_id,
        event=LogEvent.GENERIC,
        level=LogLevel.INFO,
        fields={"detail": message.strip()},
        message=message,
    )["msg"]


def account_log(
    account_id: str,
    message: str,
    *,
    level: str = "info",
    event: LogEvent | str | None = None,
    cycle: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    if event is not None:
        line = account_log_line(account_id, event, level, cycle=cycle, **(extra or {}))
        return line
    line = account_log_line(
        account_id,
        LogEvent.GENERIC,
        level,
        cycle=cycle,
        detail=message.strip(),
    )
    return line
