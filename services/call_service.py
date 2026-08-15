"""CRM call scheduling — reminders, links, WebSocket updates."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from core import broadcast
from core.call_store import (
    CALL_TYPES,
    LIVE_CALL_MESSAGE,
    cancel_call,
    complete_call,
    get_call,
    get_last_live_call_attempt,
    list_calls,
    log_live_call_attempt,
    schedule_call,
)
from core.crm_store import get_lead, upsert_lead
from services import crm_service


def _parse_iso(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _call_key(slot: str, user_id: int) -> str:
    return f"{slot}:{int(user_id)}"


def list_scheduled_calls() -> dict[str, dict]:
    out = {}
    now = time.time()
    for key, call in list_calls().items():
        if call.get("status") != "scheduled":
            continue
        st = _parse_iso(call.get("scheduled_time"))
        if st is not None and st < now - 3600:
            continue
        out[key] = dict(call)
    return out


def list_call_reminders(within_minutes: float = 5.0) -> list[dict]:
    now = time.time()
    window = float(within_minutes) * 60
    due = []
    for key, call in list_calls().items():
        if call.get("status") != "scheduled":
            continue
        st = _parse_iso(call.get("scheduled_time"))
        if st is None:
            continue
        delta = st - now
        if 0 <= delta <= window:
            due.append({**call, "lead_key": key, "minutes_until": max(0, int(delta / 60))})
    due.sort(key=lambda x: x.get("scheduled_time") or "")
    return due


def list_past_due_calls() -> list[dict]:
    """Scheduled calls whose time passed — prompt for outcome."""
    now = time.time()
    past = []
    for key, call in list_calls().items():
        if call.get("status") != "scheduled":
            continue
        st = _parse_iso(call.get("scheduled_time"))
        if st is not None and st <= now:
            past.append({**call, "lead_key": key})
    past.sort(key=lambda x: x.get("scheduled_time") or "")
    return past


def build_call_link(call: dict) -> dict:
    """Return { url, label, can_open } for Start Call."""
    ct = call.get("call_type") or "telegram"
    username = (call.get("username") or "").strip().lstrip("@")
    phone = "".join(c for c in str(call.get("phone") or "") if c.isdigit())
    uid = int(call.get("user_id") or 0)

    if ct == "whatsapp":
        if phone:
            return {"url": f"https://wa.me/{phone}", "label": "Open WhatsApp", "can_open": True}
        if username:
            return {
                "url": f"https://t.me/{username}",
                "label": "Open Telegram (no WhatsApp number on file)",
                "can_open": True,
            }
        return {"url": None, "label": "No phone number — ask lead on chat", "can_open": False}

    if ct == "phone":
        if phone:
            return {"url": f"tel:+{phone}", "label": "Call number", "can_open": True}
        return {"url": None, "label": "No phone number saved for this lead", "can_open": False}

    if username:
        return {"url": f"https://t.me/{username}", "label": "Open Telegram", "can_open": True}
    if uid:
        return {"url": f"tg://user?id={uid}", "label": "Open Telegram profile", "can_open": True}
    return {"url": None, "label": "No Telegram username for this lead", "can_open": False}


def resolve_contact(slot: str, user_id: int) -> dict:
    """Lead + inbox row contact info for call links."""
    lead = get_lead(slot, user_id) or {}
    name = lead.get("name") or ""
    username = lead.get("username") or ""
    phone = lead.get("phone") or ""
    from core.dm_store import list_conversations

    for c in list_conversations(slot):
        if int(c.get("user_id") or 0) == int(user_id):
            name = name or c.get("name") or ""
            username = username or c.get("username") or ""
            break
    return {
        "user_id": int(user_id),
        "account_id": slot,
        "name": name,
        "username": username,
        "phone": phone,
    }


def build_live_call_options(contact: dict) -> list[dict]:
    """Options for Call Now modal with can_open flags."""
    username = (contact.get("username") or "").strip().lstrip("@")
    phone = "".join(c for c in str(contact.get("phone") or "") if c.isdigit())
    uid = int(contact.get("user_id") or 0)
    options = []

    options.append({
        "id": "whatsapp",
        "label": "WhatsApp Call",
        "hint": "Opens WhatsApp — tap call there" if phone else "No phone number on file",
        "can_open": bool(phone),
        "url": f"https://wa.me/{phone}" if phone else None,
    })
    options.append({
        "id": "phone",
        "label": "Phone Call",
        "hint": "Opens your phone dialer" if phone else "No phone number on file",
        "can_open": bool(phone),
        "url": f"tel:+{phone}" if phone else None,
    })
    tg_url = f"https://t.me/{username}" if username else (f"tg://user?id={uid}" if uid else None)
    options.append({
        "id": "telegram",
        "label": "Telegram (open chat)",
        "hint": (
            "Open chat — use Telegram voice call"
            if (username or uid)
            else "No Telegram username"
        ),
        "can_open": bool(username or uid),
        "url": tg_url,
    })
    return options


def enrich_call_fields(slot: str, conv: dict) -> dict:
    uid = int(conv.get("user_id") or 0)
    out = dict(conv)
    call = get_call(slot, uid)
    if call and call.get("status") == "scheduled":
        out["crm_scheduled_call"] = call
    last_live = get_last_live_call_attempt(slot, uid)
    if last_live:
        out["crm_last_live_call"] = last_live
    return out


def build_calls_payload() -> dict:
    return {
        "scheduled_calls": list_scheduled_calls(),
        "call_reminders": list_call_reminders(),
        "past_due_calls": list_past_due_calls(),
        "call_types": sorted(CALL_TYPES),
    }


async def schedule_lead_call(
    slot: str,
    user_id: int,
    *,
    scheduled_time: str,
    call_type: str,
    notes: str = "",
) -> dict:
    from services.block_service import assert_not_blocked

    assert_not_blocked(slot, user_id)
    lead = get_lead(slot, user_id) or {}
    name = lead.get("name") or ""
    username = lead.get("username") or ""
    if not name or not username:
        from core.dm_store import list_conversations

        for c in list_conversations(slot):
            if int(c.get("user_id") or 0) == int(user_id):
                name = name or c.get("name") or ""
                username = username or c.get("username") or ""
                break
    call = schedule_call(
        slot,
        user_id,
        scheduled_time=scheduled_time,
        call_type=call_type,
        notes=notes,
        name=name,
        username=username,
        phone=lead.get("phone") or "",
    )
    upsert_lead(slot, user_id, status="follow_up")
    await broadcast_call_update(slot, user_id, call)
    return call


async def complete_lead_call(
    slot: str,
    user_id: int,
    *,
    outcome_status: str | None = None,
) -> dict | None:
    from core.crm_store import CRM_STATUSES

    call = complete_call(slot, user_id, outcome_status=outcome_status)
    if outcome_status and outcome_status in CRM_STATUSES:
        await crm_service.update_lead(slot, user_id, status=outcome_status)
    await broadcast_call_update(slot, user_id, call or {})
    return call


async def initiate_live_call(
    slot: str,
    user_id: int,
    *,
    call_type: str,
    send_message: bool = True,
) -> dict:
    from services.block_service import assert_not_blocked

    assert_not_blocked(slot, user_id)
    contact = resolve_contact(slot, user_id)
    options = build_live_call_options(contact)
    chosen = next((o for o in options if o["id"] == call_type), None)
    if not chosen or not chosen.get("can_open"):
        raise ValueError(f"Cannot start {call_type} call — missing contact info")

    attempt = log_live_call_attempt(
        slot,
        user_id,
        call_type=call_type,
        name=contact.get("name") or "",
        username=contact.get("username") or "",
        phone=contact.get("phone") or "",
    )
    upsert_lead(slot, user_id, touch_contact=True, outgoing=True)

    sent_message = None
    conversation = None
    if send_message:
        from services.dm_inbox_service import run_dm_send

        try:
            result = await run_dm_send(slot, int(user_id), LIVE_CALL_MESSAGE)
            sent_message = result.get("message")
            conversation = result.get("conversation")
        except Exception:
            pass

    await broadcast_call_update(slot, user_id, attempt, event="live_call")
    return {
        "attempt": attempt,
        "link": chosen,
        "options": options,
        "message": sent_message,
        "conversation": conversation,
        "auto_message_text": LIVE_CALL_MESSAGE,
    }


async def broadcast_call_update(
    slot: str,
    user_id: int,
    call: dict,
    *,
    event: str = "call_updated",
) -> None:
    from services.dm_inbox_service import build_slot_payload

    conv_row = None
    for c in build_slot_payload(slot).get("conversations") or []:
        if int(c.get("user_id") or 0) == int(user_id):
            conv_row = crm_service.enrich_conversation(slot, c)
            conv_row = enrich_call_fields(slot, conv_row)
            break
    payload = crm_service.build_crm_payload()
    payload.update(build_calls_payload())
    await broadcast.broadcast({
        "type": "crm",
        "event": event,
        "slot": slot,
        "user_id": int(user_id),
        "call": call,
        "live_call": call if event == "live_call" else None,
        "conversation": conv_row,
        "crm": payload,
    })
