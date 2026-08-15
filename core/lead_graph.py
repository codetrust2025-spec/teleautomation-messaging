"""Marketing lead graph — links Telegram DMs, Karthik AI, and CRM.

One logical lead is keyed by ``slot:user_id``. This module keeps AI
qualification and stage in sync with CRM.
"""

from __future__ import annotations

import hashlib
import re

from core.ai_smart_reply_store import (
    STAGE_CTA,
    STAGE_QUALIFY,
    STAGE_VALUE,
    get_lead_state,
)
from core.crm_store import CRM_INACTIVE_STATUSES, get_lead, upsert_lead

STAGE_TO_CRM_STATUS = {
    STAGE_QUALIFY: "interested",
    STAGE_VALUE: "interested",
    STAGE_CTA: "follow_up",
}

CRM_STATUS_RANK = {
    "new": 0,
    "interested": 1,
    "follow_up": 2,
    "converted": 3,
    "not_interested": 90,
    "spam": 91,
}

QUAL_LABELS = {
    "tech_stack": "Tech",
    "experience": "Experience",
    "service_need": "Service",
    "urgency": "Urgency",
    "round_type": "Round",
    "interview_timing": "Interview",
    "domain": "Domain",
    "location": "Location",
    "phone": "Phone",
    "deferral": "Follow-up",
}

KARTHIK_NOTE_PREFIX = "[Karthik]"


def lead_key(slot: str, user_id: int) -> str:
    return f"{slot}:{int(user_id)}"


def _qual_hash(qual: dict) -> str:
    items = sorted(
        (k, str(v))
        for k, v in (qual or {}).items()
        if v not in (None, "", "unknown")
    )
    if not items:
        return ""
    return hashlib.md5(repr(items).encode()).hexdigest()[:12]


def format_qualification_summary(qual: dict | None) -> str:
    parts: list[str] = []
    for key, label in QUAL_LABELS.items():
        val = (qual or {}).get(key)
        if val not in (None, "", "unknown"):
            parts.append(f"{label}: {val}")
    return " | ".join(parts)


def _notes_with_karthik_line(existing_notes: str, line: str) -> str:
    kept = [
        row
        for row in (existing_notes or "").split("\n")
        if not row.strip().startswith(KARTHIK_NOTE_PREFIX)
    ]
    kept.append(f"{KARTHIK_NOTE_PREFIX} {line}")
    return "\n".join(row for row in kept if row is not None).strip()


def sync_ai_to_crm(
    slot: str,
    user_id: int,
    *,
    stage: str | None = None,
    qualification: dict | None = None,
) -> dict | None:
    """Push Karthik stage/facts into CRM (upgrade-only for status)."""
    lead = get_lead(slot, user_id)
    if not lead:
        lead = upsert_lead(slot, int(user_id))

    status = lead.get("status") or "new"
    if status in CRM_INACTIVE_STATUSES:
        return lead

    patch: dict = {}
    graph = dict(lead.get("graph") or {})

    if stage and stage in STAGE_TO_CRM_STATUS:
        target = STAGE_TO_CRM_STATUS[stage]
        current_rank = CRM_STATUS_RANK.get(status, 0)
        target_rank = CRM_STATUS_RANK.get(target, 0)
        if target_rank > current_rank:
            patch["status"] = target

    qual = dict(qualification or {})
    if qual:
        new_hash = _qual_hash(qual)
        if new_hash and new_hash != graph.get("qual_hash"):
            summary = format_qualification_summary(qual)
            if summary:
                patch["notes"] = _notes_with_karthik_line(lead.get("notes") or "", summary)
                graph["qual_hash"] = new_hash
                graph["last_qualification"] = qual
        phone = str(qual.get("phone") or "").strip()
        if phone:
            try:
                from core.contact_link_store import link_phone

                link_phone(slot, int(user_id), phone, linked_by="auto")
            except Exception:
                pass

    if stage:
        graph["ai_stage"] = stage

    if graph != dict(lead.get("graph") or {}):
        patch["graph"] = graph

    if not patch:
        return lead

    return upsert_lead(slot, int(user_id), **patch)


def _mine_phone_from_history(slot: str, user_id: int) -> str:
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    blob = " ".join(
        (m.get("text") or m.get("content") or "")
        for m in (conv.get("messages") or [])
        if m.get("direction") == "in"
    )
    match = re.search(r"(?:\+91|91)?[\s-]?([6-9]\d{9})", blob)
    return match.group(1) if match else ""
