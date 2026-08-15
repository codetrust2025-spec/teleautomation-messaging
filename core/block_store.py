"""CRM block list — spam / blocked leads (separate from group dead lists)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from threading import Lock

from core.config import DATA_DIR

BLOCK_REASON_SPAM = "spam"

_BLOCK_FILE = os.path.join(DATA_DIR, "crm", "block_list.json")
_lock = Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(slot: str, user_id: int) -> str:
    return f"{slot}:{int(user_id)}"


def _empty() -> dict:
    return {"blocked": {}, "updated_at": _now_iso()}


def _load() -> dict:
    with _lock:
        if not os.path.exists(_BLOCK_FILE):
            return _empty()
        try:
            with open(_BLOCK_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _empty()
            data.setdefault("blocked", {})
            return data
        except (json.JSONDecodeError, OSError):
            return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(_BLOCK_FILE), exist_ok=True)
    data["updated_at"] = _now_iso()
    with _lock:
        tmp = _BLOCK_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _BLOCK_FILE)


def is_blocked(slot: str, user_id: int) -> bool:
    key = _key(slot, user_id)
    return key in (_load().get("blocked") or {})


def get_block_entry(slot: str, user_id: int) -> dict | None:
    key = _key(slot, user_id)
    row = _load().get("blocked", {}).get(key)
    return dict(row) if row else None


def list_blocked() -> dict[str, dict]:
    return dict(_load().get("blocked") or {})


def add_to_block_list(
    slot: str,
    user_id: int,
    *,
    username: str = "",
    name: str = "",
    reason: str = BLOCK_REASON_SPAM,
) -> dict:
    key = _key(slot, user_id)
    data = _load()
    entry = {
        "user_id": int(user_id),
        "account_id": slot,
        "username": str(username or "").strip().lstrip("@"),
        "name": str(name or "").strip(),
        "blocked_at": _now_iso(),
        "reason": str(reason or BLOCK_REASON_SPAM).strip().lower() or BLOCK_REASON_SPAM,
    }
    data["blocked"][key] = entry
    _save(data)
    return dict(entry)


def remove_from_block_list(slot: str, user_id: int) -> bool:
    key = _key(slot, user_id)
    data = _load()
    if key not in data.get("blocked", {}):
        return False
    del data["blocked"][key]
    _save(data)
    return True
