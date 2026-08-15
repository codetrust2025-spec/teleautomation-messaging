"""In-app voice call sessions — WebRTC coordination, history, analytics."""

from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from threading import Lock

from core.config import DATA_DIR

CALL_STATUSES = frozenset({
    "ringing", "connecting", "active", "ended", "missed", "failed", "declined",
})
OUTCOME_TAGS = frozenset({
    "interested", "follow_up", "not_available", "not_qualified", "closed",
})

_SESSIONS_FILE = os.path.join(DATA_DIR, "crm", "voice_calls.json")
_lock = Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lead_key(slot: str, user_id: int) -> str:
    return f"{slot}:{int(user_id)}"


def _empty() -> dict:
    return {"sessions": {}, "by_lead": {}, "updated_at": _now_iso()}


def _load() -> dict:
    with _lock:
        if not os.path.exists(_SESSIONS_FILE):
            return _empty()
        try:
            with open(_SESSIONS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _empty()
            data.setdefault("sessions", {})
            data.setdefault("by_lead", {})
            return data
        except (json.JSONDecodeError, OSError):
            return _empty()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(_SESSIONS_FILE), exist_ok=True)
    data["updated_at"] = _now_iso()
    with _lock:
        tmp = _SESSIONS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _SESSIONS_FILE)


def _new_join_token() -> str:
    return secrets.token_urlsafe(24)


def create_session(
    slot: str,
    user_id: int,
    *,
    caller: str = "",
    assigned_to: str = "",
    lead_name: str = "",
    lead_username: str = "",
) -> dict:
    session_id = str(uuid.uuid4())[:12]
    join_token = _new_join_token()
    now = _now_iso()
    session = {
        "id": session_id,
        "join_token": join_token,
        "account_id": slot,
        "user_id": int(user_id),
        "caller": str(caller or "").strip() or "operator",
        "assigned_to": str(assigned_to or caller or "").strip() or "operator",
        "lead_name": str(lead_name or "").strip(),
        "lead_username": str(lead_username or "").strip().lstrip("@"),
        "status": "ringing",
        "direction": "outbound",
        "started_at": now,
        "connected_at": None,
        "ended_at": None,
        "duration_sec": 0,
        "outcome": "",
        "notes": "",
        "ai_summary": "",
        "ai_suggested_action": "",
        "recording_url": "",
        "events": [{"at": now, "status": "ringing", "by": caller or "operator"}],
        "created_at": now,
    }
    data = _load()
    data["sessions"][session_id] = session
    key = _lead_key(slot, user_id)
    lead_ids = list(data["by_lead"].get(key) or [])
    lead_ids.append(session_id)
    data["by_lead"][key] = lead_ids[-100:]
    _save(data)
    return dict(session)


def get_session(session_id: str) -> dict | None:
    row = _load().get("sessions", {}).get(session_id)
    return dict(row) if row else None


def find_session_by_telegram_call_id(slot: str, call_id: int) -> dict | None:
    """Recover active call session after listener reconnect or memory loss."""
    cid = int(call_id or 0)
    if not cid or not slot:
        return None
    for row in _load().get("sessions", {}).values():
        if row.get("account_id") != slot:
            continue
        if int(row.get("telegram_call_id") or 0) != cid:
            continue
        if row.get("status") in ("ringing", "connecting", "active"):
            return dict(row)
    return None


def get_session_by_token(join_token: str) -> dict | None:
    token = str(join_token or "").strip()
    if not token:
        return None
    for row in _load().get("sessions", {}).values():
        if row.get("join_token") == token:
            return dict(row)
    return None


def update_session(session_id: str, **fields) -> dict | None:
    data = _load()
    session = data.get("sessions", {}).get(session_id)
    if not session:
        return None
    session = dict(session)
    status = fields.pop("status", None)
    event_by = fields.pop("event_by", "")
    if status and status in CALL_STATUSES:
        session["status"] = status
        session.setdefault("events", []).append({
            "at": _now_iso(),
            "status": status,
            "by": event_by or session.get("caller") or "system",
        })
    for k, v in fields.items():
        if v is not None:
            session[k] = v
    data["sessions"][session_id] = session
    _save(data)
    return dict(session)


def end_session(
    session_id: str,
    *,
    status: str = "ended",
    outcome: str = "",
    notes: str = "",
    ai_summary: str = "",
    ai_suggested_action: str = "",
) -> dict | None:
    session = get_session(session_id)
    if not session:
        return None
    now = _now_iso()
    duration = 0
    connected_at = session.get("connected_at")
    if connected_at:
        try:
            start = datetime.fromisoformat(str(connected_at).replace("Z", "+00:00"))
            end = datetime.fromisoformat(now.replace("Z", "+00:00"))
            duration = max(0, int((end - start).total_seconds()))
        except (TypeError, ValueError):
            duration = 0
    st = status if status in CALL_STATUSES else "ended"
    if st == "ended" and not connected_at:
        st = "missed"
    return update_session(
        session_id,
        status=st,
        ended_at=now,
        duration_sec=duration,
        outcome=str(outcome or "").strip().lower(),
        notes=str(notes or "").strip(),
        ai_summary=str(ai_summary or "").strip(),
        ai_suggested_action=str(ai_suggested_action or "").strip(),
        event_by="system",
    )


def list_lead_sessions(slot: str, user_id: int, *, limit: int = 30) -> list[dict]:
    key = _lead_key(slot, user_id)
    data = _load()
    ids = list(data.get("by_lead", {}).get(key) or [])
    out: list[dict] = []
    for sid in reversed(ids):
        row = data.get("sessions", {}).get(sid)
        if row:
            out.append(dict(row))
        if len(out) >= limit:
            break
    return out


def list_recent_sessions(*, limit: int = 200) -> list[dict]:
    rows = [dict(r) for r in _load().get("sessions", {}).values()]
    rows.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    return rows[:limit]


def analytics_summary(*, days: int = 30) -> dict:
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    total = answered = missed = 0
    duration_total = 0
    by_caller: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    for row in _load().get("sessions", {}).values():
        started = row.get("started_at")
        try:
            ts = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if ts < cutoff:
            continue
        total += 1
        st = row.get("status") or ""
        if st == "active" or row.get("connected_at"):
            answered += 1
        if st == "missed":
            missed += 1
        duration_total += int(row.get("duration_sec") or 0)
        caller = row.get("caller") or "unknown"
        by_caller[caller] = by_caller.get(caller, 0) + 1
        oc = row.get("outcome") or "unset"
        by_outcome[oc] = by_outcome.get(oc, 0) + 1
    avg_duration = int(duration_total / answered) if answered else 0
    return {
        "days": days,
        "total_calls": total,
        "answered": answered,
        "missed": missed,
        "answer_rate": round((answered / total * 100) if total else 0, 1),
        "avg_duration_sec": avg_duration,
        "by_caller": by_caller,
        "by_outcome": by_outcome,
    }
