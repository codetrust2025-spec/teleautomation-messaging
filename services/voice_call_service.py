"""In-app voice calls — session lifecycle, timeline, signaling, AI summaries."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from core import broadcast, voice_signaling
from core.voice_call_store import (
    OUTCOME_TAGS,
    create_session,
    end_session,
    get_session,
    get_session_by_token,
    list_lead_sessions,
    list_recent_sessions,
    analytics_summary,
    update_session,
)

logger = logging.getLogger(__name__)

DEFAULT_JOIN_DM = (
    "📞 Voice call — tap this link to talk (allow microphone when asked):\n"
    "{join_url}\n"
    "Please use this link for voice."
)

HYBRID_CALL_DM = (
    "📞 Voice call — tap to join (allow microphone):\n"
    "{join_url}\n"
    "Please use this link for voice."
)

TELEGRAM_INCOMING_REDIRECT_DM = (
    "📞 Got your Telegram call! Tap here to talk in your browser — I'm waiting on the line:\n"
    "{join_url}"
)


def _public_base_url() -> str:
    return (
        os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("DASHBOARD_PUBLIC_URL")
        or os.environ.get("PUBLIC_CALL_BASE_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


def build_join_url(join_token: str) -> str:
    return f"{_public_base_url()}/call/join/{join_token}"


def _call_timeline_text(session: dict, event: str) -> str:
    name = session.get("lead_name") or session.get("lead_username") or "Lead"
    caller = session.get("caller") or "Team"
    if event == "ringing":
        return f"📞 Outgoing call to {name} — ringing…"
    if event == "connecting":
        return f"📞 Call with {name} — connecting…"
    if event == "active":
        return f"📞 Call with {name} — connected"
    if event == "missed":
        return f"📵 Missed call with {name}"
    if event == "ended":
        dur = int(session.get("duration_sec") or 0)
        mins = dur // 60
        secs = dur % 60
        label = f"{mins}m {secs}s" if mins else f"{secs}s"
        outcome = session.get("outcome") or ""
        suffix = f" · {outcome.replace('_', ' ')}" if outcome else ""
        return f"📞 Call ended ({label}){suffix}"
    return f"📞 Call update — {event}"


async def _append_timeline_event(
    slot: str,
    user_id: int,
    session: dict,
    *,
    event: str,
) -> dict | None:
    from core.dm_store import append_message, load_inbox
    from services import dm_inbox_service

    lead_name = session.get("lead_name") or ""
    username = session.get("lead_username") or ""
    text = _call_timeline_text(session, event)
    conv, msg, _created = append_message(
        slot,
        user_id=int(user_id),
        username=username,
        name=lead_name,
        text=text,
        direction="system",
        media="call_event",
        extra={
            "call_id": session.get("id"),
            "call_event": event,
            "call_status": session.get("status"),
            "duration_sec": session.get("duration_sec") or 0,
            "caller": session.get("caller") or "",
            "outcome": session.get("outcome") or "",
            "ai_summary": session.get("ai_summary") or "",
        },
    )
    payload = dm_inbox_service.build_slot_payload(slot)
    await broadcast.broadcast({
        "type": "inbox",
        "event": "call_event",
        "slot": slot,
        "user_id": int(user_id),
        "message": msg,
        "conversation": conv,
        "inbox": payload,
    })
    return msg


async def start_voice_call(
    slot: str,
    user_id: int,
    *,
    caller: str = "",
    assigned_to: str = "",
    send_join_dm: bool = False,
    dm_text: str | None = None,
    timeline_event: str = "ringing",
    call_mode: str = "browser",
) -> dict:
    from services.block_service import assert_not_blocked
    from services.call_service import resolve_contact

    assert_not_blocked(slot, user_id)
    # End any stuck native Telegram call so the lead is not left on "Connecting…"
    try:
        from services import telegram_call_service

        await telegram_call_service.discard_native_call(slot)
    except Exception:
        pass
    contact = resolve_contact(slot, user_id)
    session = create_session(
        slot,
        user_id,
        caller=caller,
        assigned_to=assigned_to or caller,
        lead_name=contact.get("name") or "",
        lead_username=contact.get("username") or "",
    )
    join_url = build_join_url(session["join_token"])
    session["join_url"] = join_url
    update_session(session["id"], call_mode=str(call_mode or "browser"))

    from core.crm_store import upsert_lead

    upsert_lead(slot, user_id, touch_contact=True, outgoing=True)
    await _append_timeline_event(slot, user_id, session, event=timeline_event)

    sent_message = None
    if send_join_dm:
        from services.dm_inbox_service import run_dm_send

        text = (dm_text or DEFAULT_JOIN_DM).format(join_url=join_url)
        try:
            result = await run_dm_send(slot, int(user_id), text, sent_by="operator")
            sent_message = result.get("message")
        except Exception as e:
            logger.warning("voice call join DM failed %s %s: %s", slot, user_id, e)

    await _broadcast_session(session, event="started")
    session = get_session(session["id"]) or session
    return {
        "session": session,
        "join_url": join_url,
        "sent_message": sent_message,
        "call_mode": call_mode,
    }


async def offer_web_call_for_telegram_incoming(
    slot: str,
    user_id: int,
    *,
    name: str = "",
    username: str = "",
    send_join_dm: bool = False,
) -> dict:
    """Optional browser join session when lead calls via Telegram app.

    By default we do NOT auto-DM a join link — the lead already placed a native
    Telegram call. Set ``send_join_dm=True`` only when explicitly redirecting.
    """
    reused = False
    session = None
    join_url = ""
    for row in list_lead_sessions(slot, int(user_id), limit=5):
        if row.get("status") in ("ringing", "connecting", "active"):
            session = row
            join_url = build_join_url(row["join_token"])
            reused = True
            break
    if not session:
        out = await start_voice_call(
            slot,
            int(user_id),
            caller="telegram_incoming",
            send_join_dm=send_join_dm,
            dm_text=TELEGRAM_INCOMING_REDIRECT_DM if send_join_dm else None,
            timeline_event="ringing",
        )
        return out
    if send_join_dm and join_url:
        from services.dm_inbox_service import run_dm_send

        text = TELEGRAM_INCOMING_REDIRECT_DM.format(join_url=join_url)
        try:
            await run_dm_send(slot, int(user_id), text, sent_by="operator")
        except Exception as e:
            logger.warning("telegram incoming redirect DM %s %s: %s", slot, user_id, e)
    return {"session": session, "join_url": join_url, "reused": reused}


async def start_telegram_native_call(
    slot: str,
    user_id: int,
    *,
    caller: str = "",
    assigned_to: str = "",
) -> dict:
    """Ring the lead via native Telegram VoIP — no chat messages."""
    from services.block_service import assert_not_blocked
    from services.call_service import resolve_contact
    from services import telegram_call_service

    assert_not_blocked(slot, user_id)
    contact = resolve_contact(slot, user_id)

    from services import tgcalls_service

    if tgcalls_service.is_outbound_active(slot) or telegram_call_service.is_outbound_active(slot):
        raise ValueError("Call already in progress — end it first or wait 30 seconds")

    session = create_session(
        slot,
        user_id,
        caller=caller,
        assigned_to=assigned_to or caller,
        lead_name=contact.get("name") or "",
        lead_username=contact.get("username") or "",
    )
    update_session(session["id"], call_mode="telegram")

    from core.crm_store import upsert_lead

    upsert_lead(slot, user_id, touch_contact=True, outgoing=True)

    try:
        tg = await tgcalls_service.start_outgoing_call(
            slot,
            int(user_id),
            session_id=session["id"],
        )
    except Exception:
        await finish_voice_call(session["id"], status="failed", by="system")
        raise

    update_session(session["id"], status="ringing")
    session = get_session(session["id"]) or session
    await _broadcast_session(session, event="started")
    return {
        "session": session,
        "telegram_call": tg,
        "call_mode": "telegram",
    }


async def start_hybrid_call(
    slot: str,
    user_id: int,
    *,
    caller: str = "",
    assigned_to: str = "",
    send_join_dm: bool = True,
) -> dict:
    """WebRTC voice in dashboard + join link DM."""
    out = await start_voice_call(
        slot,
        user_id,
        caller=caller,
        assigned_to=assigned_to or caller,
        send_join_dm=send_join_dm,
        dm_text=HYBRID_CALL_DM if send_join_dm else None,
        timeline_event="ringing",
        call_mode="hybrid",
    )
    out["call_mode"] = "hybrid"
    return out


async def notify_client_joined(session_id: str) -> dict | None:
    """Lead opened the join link — ring the operator dashboard."""
    session = get_session(session_id)
    if not session:
        return None
    if session.get("status") in {"ended", "missed", "failed", "declined"}:
        return session
    await mark_connecting(session_id, by="client")
    await _broadcast_session(session, event="client_joining")
    return get_session(session_id)


async def mark_connecting(session_id: str, *, by: str = "operator") -> dict | None:
    session = update_session(session_id, status="connecting", event_by=by)
    if session:
        await _broadcast_session(session, event="connecting")
    return session


async def mark_active(session_id: str, *, by: str = "client") -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    session = update_session(
        session_id,
        status="active",
        connected_at=now,
        event_by=by,
    )
    if session:
        await _append_timeline_event(
            session["account_id"],
            int(session["user_id"]),
            session,
            event="active",
        )
        await _broadcast_session(session, event="active")
    return session


async def finish_voice_call(
    session_id: str,
    *,
    status: str = "ended",
    outcome: str = "",
    notes: str = "",
    by: str = "operator",
) -> dict | None:
    live = get_session(session_id)
    if live and str(live.get("call_mode") or "") == "telegram":
        slot = str(live.get("account_id") or "")
        uid = int(live.get("user_id") or 0)
        try:
            from services import telegram_call_service, tgcalls_service

            await tgcalls_service.end_outgoing_call(slot, uid)
        except Exception:
            pass
        try:
            await telegram_call_service.discard_native_call(slot)
        except Exception:
            pass
    session = end_session(
        session_id,
        status=status,
        outcome=outcome if outcome in OUTCOME_TAGS else "",
        notes=notes,
    )
    if not session:
        return None
    event = "missed" if session.get("status") == "missed" else "ended"
    await _append_timeline_event(
        session["account_id"],
        int(session["user_id"]),
        session,
        event=event,
    )
    await _broadcast_session(session, event=event)
    asyncio.create_task(_generate_ai_summary(session_id))
    return session


async def save_call_outcome(
    session_id: str,
    *,
    outcome: str,
    notes: str = "",
) -> dict | None:
    oc = str(outcome or "").strip().lower()
    if oc and oc not in OUTCOME_TAGS:
        raise ValueError(f"Invalid outcome: {outcome}")
    session = update_session(
        session_id,
        outcome=oc,
        notes=str(notes or "").strip(),
        event_by="operator",
    )
    if not session:
        return None
    from core.crm_store import upsert_lead, get_lead

    slot = session["account_id"]
    uid = int(session["user_id"])
    lead = get_lead(slot, uid) or {}
    lead_notes = str(lead.get("notes") or "").strip()
    summary_line = f"[Call {session.get('id')}] {oc or 'no outcome'}"
    if notes:
        summary_line += f" — {notes}"
    if session.get("ai_summary"):
        summary_line += f"\nAI: {session['ai_summary']}"
    merged_notes = f"{lead_notes}\n{summary_line}".strip() if lead_notes else summary_line
    upsert_lead(slot, uid, notes=merged_notes)
    if oc in {"interested", "follow_up", "closed"}:
        from services import crm_service

        status_map = {
            "interested": "interested",
            "follow_up": "follow_up",
            "closed": "converted",
        }
        mapped = status_map.get(oc)
        if mapped:
            await crm_service.update_lead(slot, uid, status=mapped)
    if oc == "follow_up":
        from services import crm_service as _crm

        await _crm.set_follow_up(slot, uid, hours=24.0)
    await _broadcast_session(session, event="outcome_saved")
    asyncio.create_task(_generate_ai_summary(session_id, force=True))
    return session


async def handle_operator_signal(session_id: str, signal: dict) -> None:
    await voice_signaling.relay_signal(session_id, "operator", signal)


async def handle_client_signal(session_id: str, signal: dict) -> None:
    await voice_signaling.relay_signal(session_id, "client", signal)
    session = get_session(session_id)
    if not session or session.get("call_mode") not in ("browser", "hybrid"):
        return
    if session.get("status") == "ringing":
        await mark_connecting(session_id, by="client")
    if session.get("status") == "connecting" and signal.get("type") == "answer":
        await mark_active(session_id, by="client")


async def _broadcast_session(session: dict, *, event: str) -> None:
    from services import crm_service

    slot = session.get("account_id") or ""
    uid = int(session.get("user_id") or 0)
    payload = crm_service.build_crm_payload()
    await broadcast.broadcast({
        "type": "voice_call",
        "event": event,
        "session": session,
        "slot": slot,
        "user_id": uid,
        "crm": payload,
    })


async def _generate_ai_summary(session_id: str, *, force: bool = False) -> None:
    session = get_session(session_id)
    if not session:
        return
    if session.get("ai_summary") and not force:
        return
    try:
        from core.voice_call_ai import summarize_call

        result = await summarize_call(session)
        if not result:
            return
        update_session(
            session_id,
            ai_summary=result.get("summary") or "",
            ai_suggested_action=result.get("suggested_action") or "",
            outcome=result.get("outcome") if result.get("outcome") in OUTCOME_TAGS else session.get("outcome"),
            event_by="ai",
        )
        refreshed = get_session(session_id)
        if refreshed:
            await _broadcast_session(refreshed, event="ai_summary")
    except Exception:
        logger.debug("voice call AI summary failed session=%s", session_id, exc_info=True)


def get_lead_call_history(slot: str, user_id: int) -> list[dict]:
    return list_lead_sessions(slot, user_id)


def get_analytics(days: int = 30) -> dict:
    return analytics_summary(days=days)


def get_public_join_info(join_token: str) -> dict | None:
    session = get_session_by_token(join_token)
    if not session:
        return None
    if session.get("status") in {"ended", "missed", "failed", "declined"}:
        return {"expired": True, "session": session}
    return {
        "session_id": session["id"],
        "lead_name": session.get("lead_name") or "Support team",
        "status": session.get("status"),
        "join_token": join_token,
    }
