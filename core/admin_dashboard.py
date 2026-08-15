"""Admin dashboard data aggregation for Karthik ops."""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime, timezone

from core.config import ACCOUNTS
from core.crm_store import CRM_INACTIVE_STATUSES, list_leads
from core.dm_store import load_inbox
from services import crm_service


def _parse_iso(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _lead_temperature(*, stage: str, status: str, qualification: dict) -> str:
    st = (status or "new").strip().lower()
    sg = (stage or "greeting").strip().lower()
    if sg in {"cta"} or st == "converted":
        return "hot"
    if sg in {"value", "qualification"} or st in {"interested", "follow_up"}:
        return "warm"
    if st in {"not_interested", "spam"} or sg == "closed":
        return "cold"
    exp = str((qualification or {}).get("experience") or "").lower()
    if exp and exp not in {"unknown", ""}:
        return "warm"
    return "cold"


def _chat_status(lead: dict, *, now: float) -> str:
    st = (lead.get("status") or "new").strip().lower()
    if st in {"converted", "not_interested", "spam"}:
        return "closed"
    alert = crm_service.compute_reply_alert_level(lead)
    if alert:
        return "waiting"
    last_at = _parse_iso(lead.get("last_message_at") or lead.get("last_user_message_at"))
    if last_at and now - last_at <= 86400:
        return "active"
    if st not in CRM_INACTIVE_STATUSES:
        return "active"
    return "closed"


def _avg_response_seconds(conv: dict) -> float | None:
    msgs = conv.get("messages") or []
    gaps: list[float] = []
    pending_in: float | None = None
    for m in msgs:
        ts = _parse_iso(m.get("timestamp"))
        if ts is None:
            continue
        if m.get("direction") == "in":
            pending_in = ts
        elif m.get("direction") == "out" and pending_in is not None:
            gaps.append(max(0.0, ts - pending_in))
            pending_in = None
    if not gaps:
        return None
    return sum(gaps) / len(gaps)


def _message_count(conv: dict) -> int:
    return len(conv.get("messages") or [])


def _recent_snippet(conv: dict, limit: int = 6) -> list[dict]:
    msgs = list(conv.get("messages") or [])[-limit:]
    out = []
    for m in msgs:
        out.append({
            "direction": m.get("direction"),
            "text": (m.get("text") or "")[:240],
            "timestamp": m.get("timestamp"),
            "ai": bool(m.get("ai")),
        })
    return out


def _merge_lead(slot: str, uid: int, conv: dict, crm_leads: dict[str, dict]) -> dict:
    """Build lead view from preloaded CRM + inbox — no extra file reads."""
    lead = dict(crm_leads.get(f"{slot}:{int(uid)}") or {})
    if conv:
        lead.setdefault("name", conv.get("name") or "")
        lead.setdefault("username", conv.get("username") or "")
        lead.setdefault("last_message", conv.get("last_message") or "")
        lead.setdefault("last_message_at", conv.get("last_message_at"))
        lead.setdefault("unread_count", conv.get("unread_count") or 0)
    lead.setdefault("status", "new")
    lead["reply_delayed"] = crm_service.compute_reply_delayed(lead)
    lead["reply_alert_level"] = crm_service.compute_reply_alert_level(lead)
    return lead


def build_dashboard(*, window_hours: float = 24.0) -> dict:
    from core.ai_smart_reply_store import get_config, get_lead_state

    window_seconds = int(max(3600, min(168 * 3600, window_hours * 3600)))
    now = time.time()
    cfg = get_config()
    monitor: dict = {}
    crm_stats = crm_service.compute_crm_stats()
    crm_leads = list_leads()
    inboxes = {slot: load_inbox(slot) for slot in ACCOUNTS}

    live_chats: list[dict] = []
    lead_rows: list[dict] = []
    drop_offs: Counter[str] = Counter()
    question_samples: Counter[str] = Counter()
    response_times: list[float] = []
    msg_counts: list[int] = []

    for slot in ACCOUNTS:
        inbox = inboxes[slot]
        for key, conv in (inbox.get("conversations") or {}).items():
            try:
                uid = int(conv.get("user_id") or key)
            except (TypeError, ValueError):
                continue
            lead = _merge_lead(slot, uid, conv, crm_leads)
            ai_state = get_lead_state(slot, uid)
            stage = ai_state.get("stage") or "greeting"
            qual = dict(ai_state.get("qualification") or {})
            status = lead.get("status") or "new"
            temp = _lead_temperature(stage=stage, status=status, qualification=qual)
            chat_st = _chat_status(lead, now=now)
            unanswered = lead.get("reply_delayed")
            avg_rt = _avg_response_seconds(conv)
            if avg_rt is not None:
                response_times.append(avg_rt)
            mc = _message_count(conv)
            msg_counts.append(mc)

            if chat_st == "waiting":
                drop_offs["waiting_reply"] += 1
            elif stage == "greeting" and mc <= 2:
                drop_offs["early_greeting"] += 1
            elif stage in {"qualification", "value"} and chat_st == "active":
                drop_offs["mid_funnel"] += 1
            elif stage == "cta":
                drop_offs["at_payment"] += 1

            last_in = (conv.get("last_message") or "")[:120]
            if last_in and conv.get("messages"):
                last_msg = conv["messages"][-1]
                if last_msg.get("direction") == "in":
                    q = re.sub(r"\s+", " ", last_in.lower())[:80]
                    question_samples[q] += 1

            flags: list[str] = []
            if unanswered:
                flags.append("no_reply")
            if lead.get("reply_alert_level") == "aggressive":
                flags.append("delayed")

            row = {
                "slot": slot,
                "user_id": uid,
                "name": lead.get("name") or conv.get("name") or f"User {uid}",
                "username": lead.get("username") or conv.get("username") or "",
                "status": chat_st,
                "crm_status": status,
                "stage": stage,
                "temperature": temp,
                "tech": qual.get("tech_stack") or "—",
                "experience": qual.get("experience") or "—",
                "last_message": conv.get("last_message") or "",
                "last_message_at": conv.get("last_message_at"),
                "unread_count": int(conv.get("unread_count") or 0),
                "flags": flags,
                "message_count": mc,
                "avg_response_sec": round(avg_rt, 1) if avg_rt is not None else None,
                "snippet": _recent_snippet(conv),
            }
            live_chats.append(row)
            lead_rows.append({
                "slot": row["slot"],
                "user_id": row["user_id"],
                "name": row["name"],
                "temperature": temp,
                "tech": row["tech"],
                "experience": row["experience"],
                "stage": stage,
                "crm_status": status,
            })

    live_chats.sort(
        key=lambda r: (
            0 if r["status"] == "waiting" else 1 if r["status"] == "active" else 2,
            -(_parse_iso(r.get("last_message_at")) or 0.0),
        ),
    )
    lead_rows.sort(key=lambda r: {"hot": 0, "warm": 1, "cold": 2}.get(r["temperature"], 3))

    total = int(crm_stats.get("total_leads") or 0)
    active = int(crm_stats.get("active_leads") or 0)
    converted = int(crm_stats.get("by_status", {}).get("converted") or 0)
    drop_off = max(0, active - converted)

    conv_rate = round((converted / total * 100), 1) if total else 0.0
    avg_resp_min = round(sum(response_times) / len(response_times) / 60, 1) if response_times else None
    avg_msgs = round(sum(msg_counts) / len(msg_counts), 1) if msg_counts else 0

    by_status = crm_stats.get("by_status") or {}
    funnel = [
        {"step": "Total leads", "count": total, "pct": 100},
        {"step": "Active", "count": active, "pct": round(active / total * 100, 1) if total else 0},
        {"step": "Interested", "count": int(by_status.get("interested") or 0), "pct": 0},
        {"step": "Follow-up", "count": int(by_status.get("follow_up") or 0), "pct": 0},
        {"step": "Converted", "count": converted, "pct": conv_rate},
    ]
    for i, step in enumerate(funnel):
        if i > 0 and total:
            funnel[i]["pct"] = round(step["count"] / total * 100, 1)

    mstats = monitor.get("stats") or {}
    sends = int(mstats.get("sends") or 0)
    success_rate = round(sends / max(1, sends + int(mstats.get("skipped") or 0)) * 100, 1)

    bugs = list(monitor.get("issues") or [])
    for item in bugs:
        item.setdefault("status", "open" if item.get("issue_type") != "duplicate_prevented" else "fixed")

    bugs.extend([
        {
            "issue_type": "double_reply_guard",
            "location": "core/ai_smart_reply.py",
            "user_impact": "Prevents duplicate AI + manual sends",
            "root_cause": "already_answered + queue cancel",
            "status": "fixed",
        },
    ])

    quality = {
        "one_reply_guard": True,
        "duplicate_prevented_24h": int(mstats.get("duplicates_prevented") or 0),
        "long_replies_24h": int(mstats.get("long_replies") or 0),
        "queue_cancelled_24h": int(mstats.get("queue_cancelled") or 0),
    }

    return {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": round(window_seconds / 3600, 1),
        "conversion": {
            "total_users": total,
            "active_users": active,
            "converted_users": converted,
            "drop_offs": drop_off,
            "conversion_rate_pct": conv_rate,
            "avg_response_minutes": avg_resp_min,
            "avg_messages_per_user": avg_msgs,
            "replied_today": int(crm_stats.get("replied_users") or 0),
            "leads_today": int(crm_stats.get("leads_today") or 0),
        },
        "funnel": funnel,
        "live_chats": live_chats[:80],
        "live_chat_summary": {
            "active": sum(1 for c in live_chats if c["status"] == "active"),
            "waiting": sum(1 for c in live_chats if c["status"] == "waiting"),
            "closed": sum(1 for c in live_chats if c["status"] == "closed"),
            "flagged": sum(1 for c in live_chats if c["flags"]),
        },
        "lead_scoring": lead_rows[:100],
        "lead_summary": {
            "hot": sum(1 for r in lead_rows if r["temperature"] == "hot"),
            "warm": sum(1 for r in lead_rows if r["temperature"] == "warm"),
            "cold": sum(1 for r in lead_rows if r["temperature"] == "cold"),
        },
        "karthik": {
            **monitor,
            "success_rate_pct": success_rate,
            "mode": cfg.get("mode"),
            "enabled": cfg.get("enabled"),
            "min_delay": cfg.get("min_delay_seconds"),
            "max_delay": cfg.get("max_delay_seconds"),
        },
        "quality": quality,
        "behavior": {
            "drop_off_points": dict(drop_offs.most_common(8)),
            "common_questions": [{"text": t, "count": c} for t, c in question_samples.most_common(10)],
        },
        "bugs": bugs[:20],
        "ai_config": {
            "enabled": cfg.get("enabled"),
            "mode": cfg.get("mode"),
            "model": cfg.get("model"),
            "min_delay_seconds": cfg.get("min_delay_seconds"),
            "max_delay_seconds": cfg.get("max_delay_seconds"),
            "human_pause_minutes": cfg.get("human_pause_minutes"),
            "work_hours_enabled": cfg.get("work_hours_enabled"),
            "work_hours_start": cfg.get("work_hours_start"),
            "work_hours_end": cfg.get("work_hours_end"),
            "knowledge_entries": len(cfg.get("knowledge_entries") or []),
        },
    }

def install_admin_dashboard(app):
    """Register /admin/dashboard for TeleAutomation Admin UI."""

    @app.get("/admin/dashboard")
    async def admin_dashboard_api(window_hours: float = 24):
        try:
            payload = build_dashboard(window_hours=float(window_hours))
            if isinstance(payload, dict) and payload.get("status") == "error":
                return payload
            return {"status": "ok", **(payload if isinstance(payload, dict) else {"data": payload})}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
