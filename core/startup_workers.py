"""Independent startup for optional background workers.

A worker that cannot start must never stop the ones after it.

Startup used to run every optional worker inside one shared ``try/except``, so
the first failure aborted every worker below it and reported a single generic
line. That is exactly how it failed in production: ``core.daily_briefing``
belongs to Operations and has never existed in this repository, so its
unguarded import raised ``ModuleNotFoundError`` on every boot, and neither the
inbox sweep nor the interview reminder loop — each carefully wrapped in its own
``try/except`` — ever ran. The guards were there; the import above them made
them unreachable.

Starting each worker through :func:`start_optional_worker` keeps one failure
local to the worker that caused it, and names that worker in the log rather
than reporting "startup background task error".
"""

from __future__ import annotations

from typing import Callable, Iterable


def start_optional_worker(
    label: str,
    start: Callable[[], object],
    *,
    log: Callable[[str], None] | None = None,
) -> bool:
    """Start one optional worker. Report failure, never propagate it.

    Returns True when the worker started. A worker whose module is missing —
    decommissioned, moved to the other service, or not yet written — is
    reported and skipped.
    """
    try:
        start()
    except Exception as exc:  # noqa: BLE001 - one worker must not fail the rest
        if log is not None:
            log(f"{label} start failed: {type(exc).__name__}: {exc}")
        return False
    return True


def start_optional_workers(
    workers: Iterable[tuple[str, Callable[[], object]]],
    *,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    """Start each worker independently. Returns the labels that started."""
    return [
        label
        for label, start in workers
        if start_optional_worker(label, start, log=log)
    ]
