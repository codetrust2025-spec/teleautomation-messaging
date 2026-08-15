"""CRM layer on top of DM inbox — lead status, notes, follow-ups."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from core import broadcast
from core.config import ACCOUNTS
from core.crm_store import CRM_INACTIVE_STATUSES, CRM_STATUSES, get_lead, list_leads, upsert_lead
from core.dm_store import load_inbox
from core.stats_reset import get_effective_cutoff


REPLY_ALERT_SOFT_SECONDS = 300  # 5 min — soft notification
REPLY_ALERT_BUZZER_SECONDS = 600  # 10 min — buzzer
REPLY_ALERT_AGGRESSIVE_SECONDS = 1200  # 20 min — aggressive alert
REPLY_SLA_SECONDS = REPLY_ALERT_BUZZER_SECONDS  # legacy alias


def _parse_iso(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _infer_reply_times_from_dm(slot: str, user_id: int) -> tuple[str | None, str | None]:
    """Last incoming / outgoing timestamps from stored DM thread."""
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id)))
    if not conv:
        return None, None
    last_in: str | None = None
    last_out: str | None = None
    for msg in conv.get("messages") or []:
        ts = msg.get("timestamp")
        if not ts:
            continue
        if msg.get("direction") == "in":
            if last_in is None or str(ts) > str(last_in):
                last_in = str(ts)
        elif msg.get("direction") == "out":
            if last_out is None or str(ts) > str(last_out):
                last_out = str(ts)
    return last_in, last_out


def ensure_reply_timestamps(slot: str, user_id: int) -> dict:
    """Backfill last_user_message_at / last_reply_at from DM history when missing."""
    lead = get_lead(slot, user_id)
    if not lead:
        return {}
    last_in, last_out = _infer_reply_times_from_dm(slot, user_id)
    kw: dict = {}
    if last_in and not lead.get("last_user_message_at"):
        kw["last_user_message_at"] = last_in
    if last_out and not lead.get("last_reply_at"):
        kw["last_reply_at"] = last_out
    if kw:
        return upsert_lead(slot, int(user_id), **kw)
    return lead


def _effective_reply_ts(lead: dict) -> float | None:
    reply_ts = _parse_iso(lead.get("last_reply_at"))
    handled_ts = _parse_iso(lead.get("reply_handled_at"))
    effective: float | None = None
    if reply_ts is not None:
        effective = reply_ts
    if handled_ts is not None:
        effective = max(effective, handled_ts) if effective is not None else handled_ts
    return effective


def _unanswered_elapsed_seconds(lead: dict) -> float | None:
    if (lead.get("status") or "new") in CRM_INACTIVE_STATUSES:
        return None
    user_ts = _parse_iso(lead.get("last_user_message_at"))
    if user_ts is None:
        return None
    effective = _effective_reply_ts(lead)
    if effective is not None and effective >= user_ts:
        return None
    return time.time() - user_ts


def compute_reply_alert_level(lead: dict) -> str | None:
    """None | soft (5m+) | buzzer (10m+) | aggressive (20m+)."""
    elapsed = _unanswered_elapsed_seconds(lead)
    if elapsed is None:
        return None
    if elapsed >= REPLY_ALERT_AGGRESSIVE_SECONDS:
        return "aggressive"
    if elapsed >= REPLY_ALERT_BUZZER_SECONDS:
        return "buzzer"
    if elapsed >= REPLY_ALERT_SOFT_SECONDS:
        return "soft"
    return None


def compute_reply_delayed(lead: dict) -> bool:
    """True when unanswered for >= 10 minutes (buzzer tier)."""
    level = compute_reply_alert_level(lead)
    return level in ("buzzer", "aggressive")


def lead_key(slot: str, user_id: int) -> str:
    return f"{slot}:{int(user_id)}"


def default_lead_for_conversation(slot: str, conv: dict) -> dict:
    uid = int(conv.get("user_id") or 0)
    existing = get_lead(slot, uid)
    if existing:
        return existing
    return upsert_lead(
        slot,
        uid,
        name=conv.get("name") or "",
        username=conv.get("username") or "",
    )


def enrich_conversation(slot: str, conv: dict) -> dict:
    """Merge CRM fields into inbox conversation row."""
    from core.block_store import is_blocked
    from core.contact_link_store import get_by_telegram
    from core.whatsapp_channel import conversation_channels
    from services.call_service import enrich_call_fields

    uid = int(conv.get("user_id") or 0)
    link = get_by_telegram(slot, uid)
    phone_e164 = conv.get("phone_e164") or (link or {}).get("phone_e164") or ""
    channels = conv.get("channels") or conversation_channels(slot, uid)
    whatsapp_linked = bool(phone_e164 or link)
    lead = get_lead(slot, uid) or default_lead_for_conversation(slot, conv)
    lead = ensure_reply_timestamps(slot, uid) or lead
    blocked = is_blocked(slot, uid)
    reminder_ts = lead.get("reminder_timestamp")
    reminder_due = False
    status = "spam" if blocked else (lead.get("status") or "new")
    if status != "spam" and reminder_ts:
        rt = _parse_iso(reminder_ts)
        if rt is not None and rt <= time.time():
            reminder_due = True
    row = {
        **conv,
        "account_id": slot,
        "crm_status": status,
        "crm_notes": lead.get("notes") or "",
        "crm_reminder_timestamp": reminder_ts,
        "crm_reminder_due": reminder_due,
        "crm_created_at": lead.get("created_at"),
        "crm_last_contact_time": lead.get("last_contact_time"),
        "crm_first_message_at": lead.get("first_message_at"),
        "crm_last_reply_at": lead.get("last_reply_at"),
        "crm_last_user_message_at": lead.get("last_user_message_at"),
        "crm_reply_handled_at": lead.get("reply_handled_at"),
        "last_user_message_at": lead.get("last_user_message_at"),
        "last_reply_time": lead.get("last_reply_at"),
        "crm_reply_delayed": compute_reply_delayed(lead),
        "crm_reply_alert_level": compute_reply_alert_level(lead),
        "crm_blocked": blocked,
        "phone_e164": phone_e164,
        "channels": channels,
        "whatsapp_linked": whatsapp_linked,
    }
    return enrich_call_fields(slot, row)


def build_crm_payload() -> dict:
    """All leads + stats for dashboard."""
    from services.call_service import build_calls_payload

    leads = list_leads()
    from services.block_service import count_blocked, list_blocked_payload

    return {
        "leads": leads,
        "stats": compute_crm_stats(),
        "due_reminders": list_due_reminders(),
        "statuses": sorted(CRM_STATUSES),
        "block_list": list_blocked_payload(),
        "blocked_count": count_blocked(),
        **build_calls_payload(),
    }


def list_due_reminders() -> list[dict]:
    now = time.time()
    due = []
    for key, lead in list_leads().items():
        rt = _parse_iso(lead.get("reminder_timestamp"))
        if rt is None or rt > now:
            continue
        if lead.get("status") in CRM_INACTIVE_STATUSES:
            continue
        due.append({**lead, "lead_key": key})
    due.sort(key=lambda x: x.get("reminder_timestamp") or "")
    return due


def compute_crm_stats() -> dict:
    cutoff = get_effective_cutoff()
    leads_today = 0
    replied_users = 0
    converted_users = 0
    spam_users = 0
    blocked_users = 0
    active_leads = 0
    by_status = {s: 0 for s in CRM_STATUSES}

    from services.block_service import count_blocked

    blocked_users = count_blocked()

    for lead in list_leads().values():
        st = lead.get("status") or "new"
        if st in by_status:
            by_status[st] += 1
        if st == "spam":
            spam_users += 1
        if st not in CRM_INACTIVE_STATUSES:
            active_leads += 1
        created = _parse_iso(lead.get("created_at"))
        if created is not None and created >= cutoff and st not in CRM_INACTIVE_STATUSES:
            leads_today += 1
        last_reply = _parse_iso(lead.get("last_reply_at"))
        if last_reply is not None and last_reply >= cutoff and st not in CRM_INACTIVE_STATUSES:
            replied_users += 1
        if st == "converted":
            last_contact = _parse_iso(lead.get("last_contact_time"))
            if last_contact is not None and last_contact >= cutoff:
                converted_users += 1

    return {
        "leads_today": leads_today,
        "replied_users": replied_users,
        "converted_users": converted_users,
        "spam_users": spam_users,
        "blocked_users": blocked_users,
        "active_leads": active_leads,
        "by_status": by_status,
        "total_leads": sum(by_status.values()),
    }


def get_lead_detail(slot: str, user_id: int) -> dict | None:
    from core.dm_store import list_conversations

    lead = get_lead(slot, user_id)
    convs = {int(c["user_id"]): c for c in list_conversations(slot)}
    conv = convs.get(int(user_id))
    if not lead and not conv:
        return None
    if not lead and conv:
        lead = default_lead_for_conversation(slot, conv)
    lead = ensure_reply_timestamps(slot, int(user_id)) or lead
    out = dict(lead)
    out["last_user_message_at"] = out.get("last_user_message_at")
    out["last_reply_time"] = out.get("last_reply_at")
    out["reply_delayed"] = compute_reply_delayed(out)
    out["reply_alert_level"] = compute_reply_alert_level(out)
    if conv:
        out["name"] = out.get("name") or conv.get("name") or ""
        out["username"] = out.get("username") or conv.get("username") or ""
        out["last_message"] = conv.get("last_message") or ""
        out["last_message_at"] = conv.get("last_message_at")
        out["unread_count"] = conv.get("unread_count") or 0
    from core.contact_link_store import get_by_telegram
    from core.whatsapp_channel import conversation_channels

    link = get_by_telegram(slot, int(user_id))
    out["phone_e164"] = out.get("phone_e164") or (conv or {}).get("phone_e164") or (link or {}).get("phone_e164") or ""
    out["channels"] = (conv or {}).get("channels") or conversation_channels(slot, int(user_id))
    out["whatsapp_linked"] = bool(out.get("phone_e164") or link)
    from core.call_store import get_call

    from core.call_store import get_last_live_call_attempt

    call = get_call(slot, int(user_id))
    if call and call.get("status") == "scheduled":
        out["scheduled_call"] = call
    last_live = get_last_live_call_attempt(slot, int(user_id))
    if last_live:
        out["last_live_call"] = last_live
    return out


async def mark_reply_handled(slot: str, user_id: int) -> dict:
    from services.block_service import assert_not_blocked

    assert_not_blocked(slot, user_id)
    lead = upsert_lead(slot, int(user_id), mark_handled=True)
    await broadcast_crm_update(slot, user_id, lead)
    return lead


async def update_lead(
    slot: str,
    user_id: int,
    *,
    status: str | None = None,
    notes: str | None = None,
    reminder_timestamp=None,
    mark_handled: bool = False,
    _has_reminder: bool = False,
) -> dict:
    from core.crm_store import _UNSET

    kw: dict = {}
    if status == "spam":
        from services.block_service import block_lead

        result = await block_lead(slot, int(user_id))
        lead = result["lead"]
        await broadcast_crm_update(slot, user_id, lead)
        return lead

    if status is not None:
        kw["status"] = status
    if notes is not None:
        kw["notes"] = notes
    if _has_reminder:
        kw["reminder_timestamp"] = reminder_timestamp
    if mark_handled:
        kw["mark_handled"] = True
    lead = upsert_lead(slot, int(user_id), **kw)
    await broadcast_crm_update(slot, user_id, lead)
    return lead


async def set_follow_up(slot: str, user_id: int, hours: float | None = None) -> dict:
    from services.block_service import assert_not_blocked

    assert_not_blocked(slot, user_id)
    if hours is None:
        ts = None
    else:
        ts = time.time() + float(hours) * 3600
    lead = upsert_lead(
        slot,
        user_id,
        status="follow_up",
        reminder_timestamp=ts,
    )
    await broadcast_crm_update(slot, user_id, lead)
    return lead


async def broadcast_crm_update(slot: str, user_id: int, lead: dict) -> None:
    conv_row = None
    from services.dm_inbox_service import build_slot_payload

    for c in build_slot_payload(slot).get("conversations") or []:
        if int(c.get("user_id") or 0) == int(user_id):
            conv_row = enrich_conversation(slot, c)
            break
    await broadcast.broadcast({
        "type": "crm",
        "event": "lead_updated",
        "slot": slot,
        "user_id": int(user_id),
        "lead": lead,
        "conversation": conv_row,
        "crm": build_crm_payload(),
    })


def touch_from_message(
    slot: str,
    user_id: int,
    *,
    direction: str,
    name: str = "",
    username: str = "",
) -> dict:
    return upsert_lead(
        slot,
        user_id,
        name=name,
        username=username,
        touch_contact=True,
        incoming=direction == "in",
        outgoing=direction == "out",
    )


def sync_leads_from_inbox() -> int:
    """Bootstrap CRM rows for existing conversations (no overwrite of status)."""
    count = 0
    for slot in ACCOUNTS:
        data = load_inbox(slot)
        for conv in (data.get("conversations") or {}).values():
            uid = int(conv.get("user_id") or 0)
            if uid <= 0:
                continue
            if not get_lead(slot, uid):
                default_lead_for_conversation(slot, conv)
                count += 1
    return count
