"""CRM lead records — separate from forwarding and raw DM history."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from threading import Lock

from core.config import DATA_DIR

CRM_STATUSES = frozenset({
    "new",
    "interested",
    "follow_up",
    "not_interested",
    "converted",
    "spam",
})

# Not counted toward active pipeline / daily engagement metrics
CRM_INACTIVE_STATUSES = frozenset({"converted", "not_interested", "spam"})

_CRM_FILE = os.path.join(DATA_DIR, "crm", "leads.json")
_lock = Lock()
_UNSET = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lead_key(slot: str, user_id: int) -> str:
    return f"{slot}:{int(user_id)}"


def _empty() -> dict:
    return {"leads": {}, "updated_at": _now_iso()}


def _load() -> dict:
    with _lock:
        if not os.path.exists(_CRM_FILE):
            return _empty()
        try:
            with open(_CRM_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _empty()
            data.setdefault("leads", {})
            return data
        except (json.JSONDecodeError, OSError):
            return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(_CRM_FILE), exist_ok=True)
    data["updated_at"] = _now_iso()
    with _lock:
        tmp = _CRM_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _CRM_FILE)


def get_lead(slot: str, user_id: int) -> dict | None:
    key = _lead_key(slot, user_id)
    lead = _load().get("leads", {}).get(key)
    return dict(lead) if lead else None


def list_leads() -> dict[str, dict]:
    return dict(_load().get("leads") or {})


def upsert_lead(
    slot: str,
    user_id: int,
    *,
    status: str | None = None,
    notes: str | None = None,
    reminder_timestamp: str | float | None = _UNSET,
    touch_contact: bool = False,
    incoming: bool = False,
    outgoing: bool = False,
    mark_handled: bool = False,
    last_user_message_at: str | None = _UNSET,
    last_reply_at: str | None = _UNSET,
    reply_handled_at: str | None = _UNSET,
    name: str | None = None,
    username: str | None = None,
) -> dict:
    """Create or update a lead. reminder_timestamp=__unset__ means do not change."""
    data = _load()
    key = _lead_key(slot, user_id)
    now = _now_iso()
    lead = dict(data["leads"].get(key) or {})
    if not lead:
        lead = {
            "user_id": int(user_id),
            "account_id": slot,
            "status": "new",
            "notes": "",
            "reminder_timestamp": None,
            "created_at": now,
            "last_contact_time": now,
            "first_message_at": None,
            "last_user_message_at": None,
            "last_reply_at": None,
            "reply_handled_at": None,
            "name": "",
            "username": "",
        }
    if name is not None:
        lead["name"] = str(name).strip()
    if username is not None:
        lead["username"] = str(username).strip().lstrip("@")
    if status is not None:
        st = str(status).strip().lower().replace(" ", "_").replace("/", "_")
        if st in ("spam_timepass", "timepass"):
            st = "spam"
        if st in CRM_STATUSES:
            lead["status"] = st
            if st == "spam":
                lead["reminder_timestamp"] = None
    if notes is not None:
        lead["notes"] = str(notes)
    if reminder_timestamp is not _UNSET:
        if reminder_timestamp is None:
            lead["reminder_timestamp"] = None
        elif isinstance(reminder_timestamp, (int, float)):
            lead["reminder_timestamp"] = datetime.fromtimestamp(
                float(reminder_timestamp), tz=timezone.utc
            ).isoformat()
        else:
            lead["reminder_timestamp"] = str(reminder_timestamp)
    if last_user_message_at is not _UNSET:
        lead["last_user_message_at"] = last_user_message_at
    if last_reply_at is not _UNSET:
        lead["last_reply_at"] = last_reply_at
    if reply_handled_at is not _UNSET:
        lead["reply_handled_at"] = reply_handled_at
    if touch_contact:
        lead["last_contact_time"] = now
    if incoming and not lead.get("first_message_at"):
        lead["first_message_at"] = now
    if incoming:
        lead["last_user_message_at"] = now
        lead["last_contact_time"] = now
    if outgoing:
        lead["last_reply_at"] = now
        lead["last_contact_time"] = now
    if mark_handled:
        lead["reply_handled_at"] = now
    data["leads"][key] = lead
    _save(data)
    return dict(lead)


def delete_lead(slot: str, user_id: int) -> bool:
    data = _load()
    key = _lead_key(slot, user_id)
    if key not in data.get("leads", {}):
        return False
    del data["leads"][key]
    _save(data)
    return True
