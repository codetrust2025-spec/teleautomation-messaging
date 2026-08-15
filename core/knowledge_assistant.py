"""Read-only natural-language access to Marketing CRM records."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

ALLOWED_INTENTS = {"stale_leads", "lead_summary", "search_leads", "marketing_briefing"}
_SESSIONS: dict[str, dict[str, Any]] = {}
_SESSION_LOCK = threading.Lock()
_SESSION_TTL_SECONDS = 30 * 60
_INACTIVE_STATUSES = {"converted", "not_interested", "spam"}


def _session(session_id: str | None) -> tuple[str, dict[str, Any]]:
    now = time.time()
    with _SESSION_LOCK:
        for key in list(_SESSIONS):
            if now - float(_SESSIONS[key].get("touched") or 0) > _SESSION_TTL_SECONDS:
                _SESSIONS.pop(key, None)
        sid = (session_id or "").strip() or uuid.uuid4().hex
        state = _SESSIONS.setdefault(sid, {"turns": [], "last_plan": {}, "touched": now})
        state["touched"] = now
        return sid, state


def end_session(session_id: str) -> bool:
    with _SESSION_LOCK:
        return _SESSIONS.pop((session_id or "").strip(), None) is not None


def _ollama_plan(question: str, context: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    prompt = f"""Convert the Marketing CRM question into exactly one JSON object.
Allowed intents: {', '.join(sorted(ALLOWED_INTENTS))}.
Schema: {{"intent":"...","name":"","days":2,"limit":25}}
Resolve follow-ups from: {json.dumps((context or [])[-4:], ensure_ascii=False)[:1800]}
Never output SQL, code, or commentary. Question: {question[:500]}"""
    try:
        payload = json.dumps({
            "model": os.getenv("OLLAMA_REASONING_MODEL", "qwen2.5:7b"),
            "stream": False,
            "format": "json",
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=float(os.getenv("OLLAMA_TEXT_TIMEOUT", "60"))) as response:
            plan = json.loads(json.loads(response.read().decode("utf-8")).get("message", {}).get("content", ""))
        return plan if plan.get("intent") in ALLOWED_INTENTS else None
    except Exception:
        return None


def _fallback_plan(question: str) -> dict[str, Any]:
    q = question.strip().lower()
    if any(word in q for word in ("briefing", "pipeline", "overview")):
        return {"intent": "marketing_briefing"}
    if "lead" in q and any(word in q for word in ("reply", "respond", "contact", "stale")):
        match = re.search(r"(\d+)\s*day", q)
        return {"intent": "stale_leads", "days": int(match.group(1)) if match else 2}
    match = re.search(r"(?:summari[sz]e|status(?:\s+of)?)\s+(.+?)(?:\?|$)", question, re.I)
    if match:
        return {"intent": "lead_summary", "name": match.group(1).strip(" .'\"")}
    return {"intent": "search_leads", "name": question.strip()}


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _matches(term: str, key: str, lead: dict[str, Any]) -> bool:
    needle = term.casefold()
    haystack = " ".join(str(lead.get(field) or "") for field in ("name", "username", "status", "notes"))
    return needle in f"{key} {haystack}".casefold()


def _evidence(key: str, lead: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "lead",
        "id": key,
        "title": lead.get("name") or lead.get("username") or key,
        "detail": f"{str(lead.get('status') or 'new').replace('_', ' ')} · account {lead.get('account_id') or 'unknown'}",
        "fields": {
            "username": lead.get("username"),
            "last_contact": lead.get("last_reply_at") or lead.get("last_contact_time"),
            "reminder": lead.get("reminder_timestamp"),
        },
    }


def answer_question(
    question: str,
    *,
    reference: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Interpret and execute one allowlisted, read-only Marketing query."""
    del reference  # Marketing records are admin-scoped, not handler-scoped.
    from core.crm_store import list_leads

    sid, session = _session(session_id)
    plan = _ollama_plan(question, session.get("turns")) or _fallback_plan(question)
    previous = session.get("last_plan") or {}
    if len(question.split()) <= 5 and plan.get("intent") == "search_leads" and previous:
        plan = {**previous, **{key: value for key, value in plan.items() if value}}

    intent = plan["intent"]
    limit = max(1, min(int(plan.get("limit") or 25), 50))
    leads = list_leads()
    evidence: list[dict[str, Any]] = []

    if intent == "stale_leads":
        days = max(1, min(int(plan.get("days") or 2), 365))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = []
        for key, lead in leads.items():
            stamp = lead.get("last_reply_at") or lead.get("last_contact_time") or lead.get("created_at")
            parsed = _parse_timestamp(stamp)
            if parsed and parsed < cutoff and lead.get("status") not in _INACTIVE_STATUSES:
                rows.append((key, lead, parsed))
        rows.sort(key=lambda row: row[2])
        evidence = [_evidence(key, lead) for key, lead, _ in rows[:limit]]
        answer = f"{len(rows)} active lead(s) have no recorded reply or contact in the last {days} days."
    elif intent == "marketing_briefing":
        active = [(key, lead) for key, lead in leads.items() if lead.get("status") not in _INACTIVE_STATUSES]
        follow_up = [(key, lead) for key, lead in active if lead.get("status") == "follow_up"]
        reminders = [(key, lead) for key, lead in active if lead.get("reminder_timestamp")]
        evidence = [_evidence(key, lead) for key, lead in (follow_up + reminders)[:limit]]
        answer = (
            f"Marketing has {len(active)} active lead(s), {len(follow_up)} marked for follow-up, "
            f"and {len(reminders)} with reminders."
        )
    else:
        term = str(plan.get("name") or question).strip()
        rows = [(key, lead) for key, lead in leads.items() if _matches(term, key, lead)]
        evidence = [_evidence(key, lead) for key, lead in rows[:limit]]
        if intent == "lead_summary" and rows:
            _, lead = rows[0]
            answer = (
                f"{lead.get('name') or lead.get('username') or 'The lead'} is currently "
                f"{str(lead.get('status') or 'new').replace('_', ' ')}."
            )
        else:
            answer = (
                f"I found {len(rows)} matching Marketing lead record(s) for “{term}”."
                if rows else f"I could not find a Marketing lead matching “{term}”."
            )

    session["last_plan"] = dict(plan)
    session["turns"] = (session.get("turns") or [])[-6:] + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer, "plan": plan},
    ]
    session["touched"] = time.time()
    return {
        "status": "ok",
        "question": question,
        "answer": answer,
        "plan": plan,
        "evidence": evidence,
        "evidence_count": len(evidence),
        "read_only": True,
        "session_id": sid,
    }
