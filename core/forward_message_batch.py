"""Smart batch settings for one-shot Forward Message jobs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from core.config import STATE_DIR

DEFAULT_BATCH_SIZE = 100
MAX_BATCH_SIZE = 100
MIN_BATCH_SIZE = 1
DEFAULT_DELAY_MIN_SECONDS = 0.5
DEFAULT_DELAY_MAX_SECONDS = 1.5
DEFAULT_BATCH_PAUSE_SECONDS = 3.0

_SETTINGS_PATH = os.path.join(STATE_DIR, "forward_message_settings.json")


@dataclass
class ForwardBatchSettings:
    batch_size: int = DEFAULT_BATCH_SIZE
    delay_min_seconds: float = DEFAULT_DELAY_MIN_SECONDS
    delay_max_seconds: float = DEFAULT_DELAY_MAX_SECONDS
    batch_pause_seconds: float = DEFAULT_BATCH_PAUSE_SECONDS

    def normalized(self) -> ForwardBatchSettings:
        bs = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, int(self.batch_size or DEFAULT_BATCH_SIZE)))
        dmin = max(0.0, float(self.delay_min_seconds))
        dmax = max(dmin, float(self.delay_max_seconds))
        pause = max(0.0, float(self.batch_pause_seconds))
        return ForwardBatchSettings(
            batch_size=bs,
            delay_min_seconds=dmin,
            delay_max_seconds=dmax,
            batch_pause_seconds=pause,
        )

    def to_dict(self) -> dict[str, Any]:
        n = self.normalized()
        return {
            "batch_size": n.batch_size,
            "batch_size_max": MAX_BATCH_SIZE,
            "delay_min_seconds": n.delay_min_seconds,
            "delay_max_seconds": n.delay_max_seconds,
            "batch_pause_seconds": n.batch_pause_seconds,
        }


def load_forward_batch_settings() -> ForwardBatchSettings:
    if not os.path.exists(_SETTINGS_PATH):
        return ForwardBatchSettings()
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return ForwardBatchSettings()
    if not isinstance(raw, dict):
        return ForwardBatchSettings()
    return ForwardBatchSettings(
        batch_size=int(raw.get("batch_size") or DEFAULT_BATCH_SIZE),
        delay_min_seconds=float(raw.get("delay_min_seconds") or DEFAULT_DELAY_MIN_SECONDS),
        delay_max_seconds=float(raw.get("delay_max_seconds") or DEFAULT_DELAY_MAX_SECONDS),
        batch_pause_seconds=float(raw.get("batch_pause_seconds") or DEFAULT_BATCH_PAUSE_SECONDS),
    ).normalized()


def save_forward_batch_settings(settings: ForwardBatchSettings) -> ForwardBatchSettings:
    os.makedirs(STATE_DIR, exist_ok=True)
    normalized = settings.normalized()
    tmp = _SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(normalized.to_dict(), f, indent=2)
    os.replace(tmp, _SETTINGS_PATH)
    return normalized


def split_into_batches(targets: list, batch_size: int) -> list[list]:
    size = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, int(batch_size or DEFAULT_BATCH_SIZE)))
    if not targets:
        return []
    return [targets[i : i + size] for i in range(0, len(targets), size)]
