"""Per-account queue limits — tunable via environment."""

from __future__ import annotations

import os

# Max pending tasks per account (backpressure threshold)
MAX_QUEUE_SIZE = int(os.environ.get("QUEUE_MAX_SIZE", "200"))

# Alert when depth reaches this fraction of max
QUEUE_HIGH_WATERMARK = float(os.environ.get("QUEUE_HIGH_WATERMARK", "0.85"))

# How long to wait when queue is full before rejecting (seconds)
QUEUE_PUT_TIMEOUT = float(os.environ.get("QUEUE_PUT_TIMEOUT", "30.0"))

# Backpressure when full: delay (wait then reject) | reject (immediate) | drop_low (evict LOW/RUN_CYCLE)
QUEUE_BACKPRESSURE_POLICY = os.environ.get("QUEUE_BACKPRESSURE_POLICY", "delay").strip().lower()

# Retry backoff + storm prevention
RETRY_MAX_ATTEMPTS = int(os.environ.get("RETRY_MAX_ATTEMPTS", "5"))
RETRY_BASE_SECONDS = float(os.environ.get("RETRY_BASE_SECONDS", "5.0"))
RETRY_MAX_SECONDS = float(os.environ.get("RETRY_MAX_SECONDS", "3600.0"))
RETRY_JITTER_RATIO = float(os.environ.get("RETRY_JITTER_RATIO", "0.15"))
RETRY_STORM_WINDOW_SECONDS = int(os.environ.get("RETRY_STORM_WINDOW_SECONDS", "60"))
RETRY_STORM_MAX_PER_ACCOUNT = int(os.environ.get("RETRY_STORM_MAX_PER_ACCOUNT", "8"))
RETRY_STORM_MAX_FLEET = int(os.environ.get("RETRY_STORM_MAX_FLEET", "40"))

# Fair cycle scheduling defaults
CYCLE_MIN_GROUPS_BEFORE_DM_YIELD = int(os.environ.get("CYCLE_MIN_GROUPS_BEFORE_DM_YIELD", "3"))
CYCLE_MAX_DM_YIELD_MS = int(os.environ.get("CYCLE_MAX_DM_YIELD_MS", "2000"))
CYCLE_MAX_WALL_SECONDS = int(os.environ.get("CYCLE_MAX_WALL_SECONDS", "5400"))

# Health monitor
HEALTH_CHECK_INTERVAL = int(os.environ.get("HEALTH_CHECK_INTERVAL", "30"))
WORKER_STALE_SECONDS = int(os.environ.get("WORKER_STALE_SECONDS", "2700"))
PROCESSOR_STALE_SECONDS = int(os.environ.get("PROCESSOR_STALE_SECONDS", "600"))
AUTO_RESTART_ON_CRASH = os.environ.get("AUTO_RESTART_ON_CRASH", "1").strip() not in (
    "0",
    "false",
    "no",
)

# Future: redis | memory
QUEUE_BACKEND = os.environ.get("QUEUE_BACKEND", "memory").strip().lower()
