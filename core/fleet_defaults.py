"""Fleet-wide defaults — shared forward link and campaign message templates."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from core.config import DATA_DIR

_DEFAULTS_FILE = os.path.join(DATA_DIR, "fleet_defaults.json")
_lock = threading.Lock()


def _load_raw() -> dict[str, Any]:
    if not os.path.exists(_DEFAULTS_FILE):
        return {}
    try:
        with open(_DEFAULTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_raw(data: dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = _DEFAULTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, _DEFAULTS_FILE)


def get_fleet_defaults() -> dict[str, Any]:
    with _lock:
        raw = _load_raw()
    from core.message_store import load_message

    return {
        "forward_source_url": str(raw.get("forward_source_url") or "").strip(),
        "campaign_message": str(raw.get("campaign_message") or "").strip() or load_message(),
    }


def save_fleet_defaults(
    *,
    forward_source_url: str | None = None,
    campaign_message: str | None = None,
) -> dict[str, Any]:
    with _lock:
        raw = _load_raw()
        if forward_source_url is not None:
            raw["forward_source_url"] = str(forward_source_url).strip()
        if campaign_message is not None:
            raw["campaign_message"] = str(campaign_message).strip()
        _save_raw(raw)
    return get_fleet_defaults()
