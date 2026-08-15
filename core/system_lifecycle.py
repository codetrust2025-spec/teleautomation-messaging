"""
Process lifecycle — restart logging, graceful shutdown, crash-loop protection.

Used by server startup/shutdown, uvicorn reload, PM2, and dev launcher.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from core.auto_reload import RestartRateGuard, reload_delay_seconds

if TYPE_CHECKING:
    from services.account_manager import AccountManager

RESTART_COUNT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    ".restart_count.json",
)

_global_restart_guard = RestartRateGuard()


def reload_delay_before_restart() -> None:
    """Debounce restarts (1–3s) to avoid tight loops."""
    delay = reload_delay_seconds()
    if delay > 0:
        time.sleep(delay)


def allow_process_restart() -> bool:
    """False when too many restarts in the last minute (crash loop)."""
    return _global_restart_guard.allow()


def log_system_event(
    message: str,
    *,
    reason: str = "system",
    detail: str = "",
) -> None:
    """
    Mandatory restart log format:
      [system] Restart triggered (file change: server.py)
    """
    prefix = "[system]"
    if reason == "file_change":
        line = f"{prefix} Restart triggered (file change{': ' + detail if detail else ''})"
    elif reason == "crash":
        line = f"{prefix} Restart triggered (crash{': ' + detail if detail else ''})"
    elif reason == "hot_reload":
        line = f"{prefix} Hot reload complete{': ' + detail if detail else ''}"
    elif reason == "cold_start":
        line = f"{prefix} Process started{': ' + detail if detail else ''}"
    elif reason == "shutdown":
        line = f"{prefix} Graceful shutdown{': ' + detail if detail else ''}"
    elif reason == "watchdog":
        line = f"{prefix} Watchdog action{': ' + detail if detail else ''}"
    else:
        line = f"{prefix} {message}"
        if detail:
            line += f" — {detail}"

    try:
        from core.worker_persistence import bump_restart_count, log_reload_event

        count = bump_restart_count()
        log_reload_event(f"{line} (restart #{count})")
    except Exception:
        pass

    print(line, flush=True)


async def graceful_shutdown(registry: "AccountManager") -> list[str]:
    """
    Before process exit (reload / PM2 restart):
    - Persist which workers were running
    - Disconnect Telethon (release SQLite sessions)
    - Do NOT clear .running_workers.json (resume after reload)
    """
    running = [
        s
        for s, runtime in registry.all_runtimes().items()
        if runtime.worker.state.running
    ]

    log_system_event(
        "Preparing for reload",
        reason="shutdown",
        detail=f"running workers: {', '.join(running) if running else 'none'}",
    )

    try:
        from core.worker_persistence import save_running_slots

        save_running_slots(running)
    except Exception:
        pass

    try:
        from core import telegram_client

        await telegram_client.disconnect_all()
    except Exception:
        pass

    return running
