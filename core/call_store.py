"""Scheduled calls per lead — separate from forwarding and DM history."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from threading import Lock

from core.config import DATA_DIR

CALL_TYPES = frozenset({"whatsapp", "phone", "telegram"})
CALL_STATUSES = frozenset({"scheduled", "completed", "cancelled"})

_CALLS_FILE = os.path.join(DATA_DIR, "crm", "calls.json")
_LIVE_LOG_FILE = os.path.join(DATA_DIR, "crm", "live_call_log.json")
_lock = Lock()

LIVE_CALL_MESSAGE = "Can we connect on a quick call now?"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _call_key(slot: str, user_id: int) -> str:
    return f"{slot}:{int(user_id)}"


def _empty() -> dict:
    return {"calls": {}, "updated_at": _now_iso()}


def _load() -> dict:
    with _lock:
        if not os.path.exists(_CALLS_FILE):
            return _empty()
        try:
            with open(_CALLS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _empty()
            data.setdefault("calls", {})
            return data
        except (json.JSONDecodeError, OSError):
            return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(_CALLS_FILE), exist_ok=True)
    data["updated_at"] = _now_iso()
    with _lock:
        tmp = _CALLS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _CALLS_FILE)


def get_call(slot: str, user_id: int) -> dict | None:
    key = _call_key(slot, user_id)
    row = _load().get("calls", {}).get(key)
    return dict(row) if row else None


def list_calls() -> dict[str, dict]:
    return dict(_load().get("calls") or {})


def schedule_call(
    slot: str,
    user_id: int,
    *,
    scheduled_time: str,
    call_type: str,
    notes: str = "",
    name: str = "",
    username: str = "",
    phone: str = "",
) -> dict:
    ct = str(call_type).strip().lower()
    if ct not in CALL_TYPES:
        ct = "telegram"
    key = _call_key(slot, user_id)
    data = _load()
    call = {
        "id": str(uuid.uuid4())[:12],
        "user_id": int(user_id),
        "account_id": slot,
        "scheduled_time": str(scheduled_time),
        "call_type": ct,
        "notes": str(notes or "").strip(),
        "status": "scheduled",
        "created_at": _now_iso(),
        "name": str(name or "").strip(),
        "username": str(username or "").strip().lstrip("@"),
        "phone": str(phone or "").strip(),
    }
    data["calls"][key] = call
    _save(data)
    return dict(call)


def complete_call(slot: str, user_id: int, *, outcome_status: str | None = None) -> dict | None:
    key = _call_key(slot, user_id)
    data = _load()
    call = data.get("calls", {}).get(key)
    if not call:
        return None
    call = dict(call)
    call["status"] = "completed"
    call["completed_at"] = _now_iso()
    if outcome_status:
        call["outcome_status"] = str(outcome_status).strip().lower()
    data["calls"][key] = call
    _save(data)
    return call


def _load_live_log() -> dict:
    with _lock:
        if not os.path.exists(_LIVE_LOG_FILE):
            return {"attempts": {}, "updated_at": _now_iso()}
        try:
            with open(_LIVE_LOG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"attempts": {}, "updated_at": _now_iso()}
            data.setdefault("attempts", {})
            return data
        except (json.JSONDecodeError, OSError):
            return {"attempts": {}, "updated_at": _now_iso()}


def _save_live_log(data: dict) -> None:
    os.makedirs(os.path.dirname(_LIVE_LOG_FILE), exist_ok=True)
    data["updated_at"] = _now_iso()
    with _lock:
        tmp = _LIVE_LOG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _LIVE_LOG_FILE)


def log_live_call_attempt(
    slot: str,
    user_id: int,
    *,
    call_type: str,
    name: str = "",
    username: str = "",
    phone: str = "",
) -> dict:
    ct = str(call_type).strip().lower()
    if ct not in CALL_TYPES:
        ct = "telegram"
    key = _call_key(slot, user_id)
    now = _now_iso()
    entry = {
        "id": str(uuid.uuid4())[:12],
        "user_id": int(user_id),
        "account_id": slot,
        "call_type": ct,
        "call_attempted": True,
        "timestamp": now,
        "name": str(name or "").strip(),
        "username": str(username or "").strip().lstrip("@"),
        "phone": str(phone or "").strip(),
    }
    data = _load_live_log()
    attempts = list(data["attempts"].get(key) or [])
    attempts.append(entry)
    data["attempts"][key] = attempts[-50:]
    data["last"] = {**(data.get("last") or {}), key: entry}
    _save_live_log(data)
    return entry


def get_last_live_call_attempt(slot: str, user_id: int) -> dict | None:
    data = _load_live_log()
    key = _call_key(slot, user_id)
    last = (data.get("last") or {}).get(key)
    if last:
        return dict(last)
    attempts = data.get("attempts", {}).get(key) or []
    return dict(attempts[-1]) if attempts else None


def delete_call_records(slot: str, user_id: int) -> None:
    """Remove scheduled call and live-call log entries for a lead."""
    key = _call_key(slot, user_id)
    data = _load()
    if key in (data.get("calls") or {}):
        del data["calls"][key]
        _save(data)
    log_data = _load_live_log()
    changed = False
    if key in (log_data.get("attempts") or {}):
        del log_data["attempts"][key]
        changed = True
    last = log_data.get("last") or {}
    if isinstance(last, dict) and key in last:
        del last[key]
        log_data["last"] = last
        changed = True
    if changed:
        _save_live_log(log_data)


def cancel_call(slot: str, user_id: int) -> bool:
    key = _call_key(slot, user_id)
    data = _load()
    call = data.get("calls", {}).get(key)
    if not call:
        return False
    call = dict(call)
    call["status"] = "cancelled"
    call["cancelled_at"] = _now_iso()
    data["calls"][key] = call
    _save(data)
    return True
