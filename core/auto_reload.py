"""
Auto-reload configuration shared by uvicorn, dev launcher, and PM2.

Save any watched file → process restarts → workers resume from data/.running_workers.json
"""

from __future__ import annotations

import os
import sys
import time

# Project root (parent of core/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories watched for code changes (not runtime data/)
RELOAD_DIRS = [
    os.path.join(ROOT, "core"),
    os.path.join(ROOT, "features"),
    os.path.join(ROOT, "workers"),
    os.path.join(ROOT, "services"),
    os.path.join(ROOT, "scripts"),
    ROOT,  # server.py, run.py — only *.py in RELOAD_INCLUDES (not data/*.json)
]

# Runtime / generated paths — never trigger reload
RELOAD_EXCLUDES = [
    "data",
    "data/*",
    "data/**",
    "static",
    "dashboard",
    "node_modules",
    "__pycache__",
    ".git",
    ".cursor",
    "reporting_data",
    "account_data",
    "logs",
    "*.session",
    "*.session-shm",
    "*.session-wal",
    "*.session-journal",
    "*.pyc",
    "*.pyo",
    "*.log",
    ".running_workers.json",
    ".restart_count.json",
    "reload.log",
    "groups_list.json",
    "group_intelligence.json",
    "account_info.json",
    "invalid_groups.json",
    "blocked_groups.json",
    "login_pending.json",
    "join_state.json",
    "**/join_state.json",
    "send_history.json",
    "**/send_history.json",
]

# Only Python + env at project root — never *.json (workers write data/accounts/*/join_state.json)
RELOAD_INCLUDES = [
    "*.py",
    "*.pyi",
    ".env",
    ".env.*",
    "server.py",
    "run.py",
]

DEFAULT_RELOAD_DELAY = 1.0
MAX_RESTARTS_PER_MINUTE = 12


def reload_enabled() -> bool:
    return os.environ.get("NO_RELOAD", "").strip().lower() not in ("1", "true", "yes")


def reload_delay_seconds() -> float:
    try:
        return max(0.3, float(os.environ.get("RELOAD_DELAY", str(DEFAULT_RELOAD_DELAY))))
    except ValueError:
        return DEFAULT_RELOAD_DELAY


def startup_kind() -> str:
    """Uvicorn reload child sets RUN_MAIN=true."""
    if os.environ.get("RUN_MAIN", "").lower() == "true":
        return "hot_reload"
    if os.environ.get("WATCHFILES_FORCE_RELOAD", ""):
        return "hot_reload"
    return "cold_start"


def _changed_files_hint() -> str:
    raw = os.environ.get("WATCHFILES_CHANGES", "").strip()
    if not raw:
        return ""
    try:
        import json

        paths = json.loads(raw)
        if isinstance(paths, list) and paths:
            return os.path.basename(str(paths[0]))
    except Exception:
        pass
    return raw[:80] if raw else ""


def log_process_start(*, version: str) -> None:
    try:
        from core.system_lifecycle import log_system_event

        kind = startup_kind()
        hint = _changed_files_hint()
        if kind == "hot_reload":
            log_system_event(
                f"Running {version}",
                reason="file_change" if hint else "hot_reload",
                detail=hint or version,
            )
        else:
            log_system_event(f"Running {version}", reason="cold_start", detail=version)
    except Exception:
        pass


def log_process_shutdown(*, running_workers: list[str]) -> None:
    """Called on FastAPI shutdown before uvicorn/PM2 restarts the process."""
    try:
        from core.system_lifecycle import log_system_event

        detail = ", ".join(running_workers) if running_workers else "no workers running"
        log_system_event("Reload imminent", reason="shutdown", detail=detail)
    except Exception:
        pass


class RestartRateGuard:
    """Prevent infinite restart loops when a file changes every second."""

    def __init__(self, max_per_minute: int = MAX_RESTARTS_PER_MINUTE):
        self._times: list[float] = []
        self._max = max_per_minute

    def allow(self) -> bool:
        now = time.time()
        self._times = [t for t in self._times if now - t < 60]
        if len(self._times) >= self._max:
            return False
        self._times.append(now)
        return True

    def wait_before_restart(self) -> None:
        delay = reload_delay_seconds()
        if delay > 0:
            time.sleep(delay)


def ensure_cwd() -> None:
    os.chdir(ROOT)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
