"""Data room service — register partners from inbox / AI detection."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import hashlib

import httpx

from services import cross_project_outbox as outbox

logger = logging.getLogger(__name__)
_dispatcher_task: asyncio.Task | None = None

_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s-]?)?(?:\d{10}|\d{5}[\s-]?\d{5})"
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def is_business_opportunity_thread(user_text: str, history: list[dict] | None) -> bool:
    from core.ai_smart_reply import (
        _user_is_vendor_partner,
        _user_offers_support_to_candidates,
        _user_seeks_dev_collaboration,
    )

    return bool(
        _user_offers_support_to_candidates(user_text, history)
        or _user_offers_support_to_candidates("", history)
        or _user_is_vendor_partner(user_text, history)
        or _user_is_vendor_partner("", history)
        or _user_seeks_dev_collaboration(user_text, history)
        or _user_seeks_dev_collaboration("", history)
    )


def _user_blob(history: list[dict] | None, user_text: str, *, tail: int = 12) -> str:
    parts: list[str] = []
    for m in (history or [])[-tail:]:
        if (m.get("role") or "").lower() in ("user", "human", "client"):
            t = (m.get("content") or "").strip()
            if t:
                parts.append(t)
    if (user_text or "").strip():
        parts.append((user_text or "").strip())
    return "\n".join(parts)


def _infer_opportunity_type(user_text: str, history: list[dict] | None) -> str:
    from core.ai_smart_reply import (
        _user_offers_support_to_candidates,
        _user_is_vendor_partner,
        _user_seeks_dev_collaboration,
    )

    if _user_offers_support_to_candidates(user_text, history):
        return "support_provider"
    if _user_seeks_dev_collaboration(user_text, history):
        return "recruitment"
    if _user_is_vendor_partner(user_text, history):
        blob = _user_blob(history, user_text).lower()
        if any(x in blob for x in ("provide support", "my support", "candidates who")):
            return "support_provider"
        return "vendor_candidates"
    return "partnership"


def _infer_tech_stack(blob: str, qualification: dict | None) -> str:
    qual = qualification or {}
    tech = (qual.get("tech_stack") or "").strip()
    if tech:
        return tech
    lower = (blob or "").lower()
    labels: list[str] = []
    checks = (
        ("java", "Java"),
        ("react", "React"),
        ("microservice", "Microservices"),
        ("python", "Python"),
        ("power bi", "Power BI"),
        ("sql", "SQL"),
        (".net", ".NET"),
        ("angular", "Angular"),
        ("node", "Node"),
        ("etl", "ETL"),
    )
    for needle, label in checks:
        if needle in lower and label not in labels:
            labels.append(label)
    return " + ".join(labels)


def _extract_contact_from_blob(blob: str) -> dict[str, str]:
    """Pull phone / WhatsApp / email from user messages (not our senior handoff)."""
    out: dict[str, str] = {}
    if not blob:
        return out
    for m in _EMAIL_RE.finditer(blob):
        email = m.group(0).strip().lower()
        if email and "@" in email:
            out["email"] = email
            break
    for m in _PHONE_RE.finditer(blob):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) >= 10:
            if len(digits) > 10 and digits.startswith("91"):
                digits = digits[-10:]
            elif len(digits) > 10:
                digits = digits[-10:]
            if len(digits) == 10:
                out["phone"] = f"+91 {digits[:5]} {digits[5:]}"
                out["whatsapp"] = digits
                break
    return out


def record_from_telegram_thread(
    slot: str,
    user_id: int,
    *,
    user_text: str = "",
    history: list[dict] | None = None,
    lead: dict | None = None,
    qualification: dict | None = None,
    opportunity_type: str | None = None,
) -> dict | None:
    """Persist partner/opportunity lead for future alignment."""
    if not is_business_opportunity_thread(user_text, history):
        return None

    from core.spam_detector import is_telegram_service_chat
    uid = int(user_id)
    lead = lead or {}
    name = (lead.get("name") or "").strip()
    username = (lead.get("username") or "").strip()
    if is_telegram_service_chat(user_text, name=name, username=username, user_id=uid):
        return None

    qual = qualification or {}
    blob = _user_blob(history, user_text)
    tech = _infer_tech_stack(blob, qual)
    otype = opportunity_type or _infer_opportunity_type(user_text, history)
    volume_hint = ""
    try:
        from core.ai_smart_reply import _provider_offers_on_job_task_support

        if _provider_offers_on_job_task_support(user_text, history):
            volume_hint = "On-job project/task support (not interview rounds)"
    except Exception:
        pass
    summary = (user_text or blob.split("\n")[-1] if blob else "")[:500]
    if volume_hint and volume_hint.lower() not in summary.lower():
        summary = f"{volume_hint}. {summary}".strip()[:500]
    snippet = blob[:1500]
    contact = _extract_contact_from_blob(blob)

    payload = {
        "slot": slot, "user_id": uid, "opportunity_type": otype,
        "name": name, "username": username, "tech_stack": tech,
        "volume_hint": volume_hint, "summary": summary, "source_snippet": snippet,
        "phone": contact.get("phone", ""), "whatsapp": contact.get("whatsapp", ""),
        "email": contact.get("email", ""), "notes_append": f"[auto] {summary[:300]}".strip(),
    }
    key = hashlib.sha256(f"opportunity|{slot}|{uid}|{summary}".encode()).hexdigest()
    outbox.enqueue(event_type="operations.opportunity.v1", idempotency_key=key, payload=payload)
    delivered = dispatch_opportunities_once()
    row = delivered.get(key)
    if row:
        logger.info("data_room saved %s:%s type=%s id=%s", slot, uid, otype, row.get("id"))
        return row
    return {"id": key, "delivery_status": "queued"}


def dispatch_opportunities_once() -> dict[str, dict]:
    """Deliver due opportunities and retain failed events for later retry."""
    base = os.getenv("OPERATIONS_INTERNAL_URL", "http://127.0.0.1:8001").rstrip("/")
    token = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
    results: dict[str, dict] = {}
    if not token:
        return results
    with httpx.Client(timeout=15.0) as client:
        for pending in outbox.due(event_type="operations.opportunity.v1"):
            key = pending["idempotency_key"]
            try:
                response = client.post(
                    f"{base}/internal/v1/opportunities",
                    json=pending["payload"],
                    headers={"X-Internal-Service-Token": token, "X-Idempotency-Key": key},
                )
                response.raise_for_status()
                body = response.json()
                outbox.mark_delivered(key)
                results[key] = body.get("opportunity") or {"id": key, "delivery_status": body.get("status")}
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                outbox.mark_failed(key, f"{type(exc).__name__}: {exc}")
    return results


async def _dispatcher_loop() -> None:
    while True:
        await asyncio.to_thread(dispatch_opportunities_once)
        await asyncio.sleep(30)


def start_outbox_dispatcher() -> None:
    global _dispatcher_task
    if _dispatcher_task is None or _dispatcher_task.done():
        _dispatcher_task = asyncio.create_task(_dispatcher_loop(), name="marketing-operations-outbox")


async def stop_outbox_dispatcher() -> None:
    global _dispatcher_task
    if _dispatcher_task is None:
        return
    _dispatcher_task.cancel()
    try:
        await _dispatcher_task
    except asyncio.CancelledError:
        pass
    _dispatcher_task = None


def backfill_from_crm(*, name_contains: str = "") -> list[dict]:
    """Scan CRM + inbox history and register matching partner threads."""
    from core.ai_smart_reply import (
        _enrich_qualification_from_history,
        _recent_conversation,
    )
    from core.crm_store import list_leads
    from core.ai_smart_reply_store import get_lead_state

    needle = (name_contains or "").strip().lower()
    saved: list[dict] = []
    for key, lead in (list_leads() or {}).items():
        name = (lead.get("name") or "").strip()
        if needle and needle not in name.lower():
            continue
        parts = key.split(":", 1)
        if len(parts) != 2:
            continue
        slot, uid_s = parts[0], parts[1]
        try:
            uid = int(uid_s)
        except ValueError:
            continue
        history = _recent_conversation(slot, uid, limit=30)
        if not history:
            continue
        last_user = ""
        for m in reversed(history):
            if (m.get("role") or "").lower() == "user":
                last_user = (m.get("content") or "").strip()
                break
        state = get_lead_state(slot, uid)
        qual = _enrich_qualification_from_history(
            slot, uid, dict(state.get("qualification") or {}),
        )
        row = record_from_telegram_thread(
            slot,
            uid,
            user_text=last_user,
            history=history,
            lead=lead,
            qualification=qual,
        )
        if row:
            saved.append(row)
    return saved
