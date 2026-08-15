"""AI-powered smart-reply engine.

End-to-end flow when a candidate sends an inbound DM:

    listener → _handle_dm_event (inbox)
            → maybe_schedule_ai_reply (this module)
            → queue task (AI_AUTO_REPLY) on the account worker
            → generate_and_send (this module)
              · gather lead + recent history
              · build OpenAI-compatible chat-completions request
              · parse {reply, next_stage, escalate, confidence, extracted_facts}
              · safety filter (length, links, banned phrases)
              · dm_inbox_service.run_dm_send with the AI text
              · persist new lead stage + qualification facts

All settings live in `core/ai_smart_reply_store` so the UI can tune them at
runtime without a restart. API key / base URL stay in env vars for safety.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone

from core.ai_smart_reply_store import (
    STAGE_CLOSED,
    STAGE_CTA,
    STAGE_GREETING,
    STAGE_QUALIFY,
    STAGE_VALUE,
    VALID_STAGES,
    account_replies_last_hour,
    get_config,
    get_lead_state,
    record_account_reply,
    record_ai_reply,
    update_lead_state,
)
from core.karthik.thread_intent import (
    INTENT_DEV_COLLAB,
    INTENT_INTERVIEW,
    INTENT_INTERVIEW_TILL_OFFER,
    INTENT_JOB_SEARCH,
    INTENT_PROXY,
    INTENT_UNKNOWN,
    has_interview_context,
    intent_blocks_dev_collab,
    intent_blocks_generic_menu,
    intent_blocks_job_search,
    intent_is_locked,
    resolve_thread_intent,
    service_need_for_intent,
    user_blob as _intent_user_blob,
)

logger = logging.getLogger("ai_smart_reply")


def _monitor(event_type: str, **kwargs) -> None:
    return


def _skip_schedule(slot: str, user_id: int, reason: str, **extra) -> None:
    logger.debug("ai_smart_reply skip schedule %s %s: %s", slot, user_id, reason)


# ── Env-driven secrets (deliberately not in JSON config) ─────────────────────
def _env_api_key() -> str:
    return (os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()


def _env_api_base() -> str:
    return (
        os.getenv("AI_API_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")


def _env_request_timeout() -> float:
    try:
        return float(os.getenv("AI_REQUEST_TIMEOUT", "25"))
    except ValueError:
        return 25.0


# ── Public API ──────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    cfg = get_config()
    if not cfg.get("enabled"):
        return False
    if not _env_api_key():
        return False
    return True


def health() -> dict:
    """For UI: tells operator whether AI is fully wired up or missing a key."""
    from core.ai_group_message import is_karthik_group_rewrite_available
    from core.ai_work_hours import work_hours_status

    cfg = get_config()
    out = {
        "enabled": bool(cfg.get("enabled")),
        "api_key_present": bool(_env_api_key()),
        "group_rewrite_enabled": bool(cfg.get("group_rewrite_enabled", True)),
        "group_rewrite_ready": is_karthik_group_rewrite_available(),
        "model": cfg.get("model"),
        "api_base": _env_api_base(),
        "work_hours": work_hours_status(cfg),
        "playbooks": _karthik_playbooks.meta(),
    }
    try:
        from core.karthik_inbox_sweep import status as sweep_status

        out["inbox_sweep"] = sweep_status()
        out["pending_inbound"] = len(list_pending_inbound_targets())
        from core.ai_llm_gateway import status as llm_gateway_status

        out["llm_gateway"] = llm_gateway_status()
    except Exception:
        pass
    return out


async def _maybe_send_off_hours_reply(
    slot: str,
    user_id: int,
    *,
    cfg: dict,
    state: dict,
    user_message_id: int | None,
) -> dict | None:
    """Outside working hours: one short offline line, then stay quiet until open."""
    from core.ai_work_hours import is_within_work_hours, next_work_window_start, offline_reply_text

    if is_within_work_hours(cfg):
        return None

    if user_message_id is not None and not _inbound_still_unanswered(
        slot, int(user_id), int(user_message_id),
    ):
        _monitor("ai_skipped", slot=slot, user_id=user_id, reason="already_answered_off_hours")
        return {"ok": False, "reason": "already_answered"}

    history = _recent_conversation(slot, int(user_id), limit=20)
    if _active_call_whatsapp_thread(history):
        _monitor("ai_skipped", slot=slot, user_id=user_id, reason="call_thread_no_off_hours")
        return {"ok": False, "reason": "active_call_thread"}

    if len(history or []) >= 4:
        _monitor("ai_skipped", slot=slot, user_id=user_id, reason="live_thread_no_off_hours")
        return {"ok": False, "reason": "active_conversation"}

    notice_until = state.get("off_hours_notice_until")
    if notice_until:
        try:
            if datetime.fromisoformat(notice_until).timestamp() > time.time():
                _monitor("ai_skipped", slot=slot, user_id=user_id, reason="off_hours_quiet")
                return {"ok": False, "reason": "off_hours_quiet"}
        except (TypeError, ValueError):
            pass

    reply_text = offline_reply_text(cfg)

    try:
        await _simulate_human_typing(slot, user_id, reply_text, cfg)
    except Exception as e:
        logger.debug("ai_smart_reply off-hours typing %s %s: %s", slot, user_id, e)

    try:
        from services.whatsapp_dispatch import dispatch_lead_reply

        send_res = await dispatch_lead_reply(
            slot, user_id, reply_text, sent_by="ai",
        )
    except Exception as e:
        logger.warning("ai_smart_reply off-hours send %s %s: %s", slot, user_id, e)
        return {"ok": False, "reason": "send_failed", "error": str(e)}

    try:
        record = send_res.get("message") or {}
        mid = record.get("id")
        if mid:
            _tag_message_as_ai(slot, user_id, int(mid), stage=STAGE_CLOSED, confidence=1.0)
    except Exception:
        pass

    nxt = next_work_window_start(cfg).isoformat()
    record_account_reply(slot)
    record_ai_reply(slot, user_id, stage=STAGE_CLOSED)
    update_lead_state(
        slot,
        user_id,
        last_user_message_id=user_message_id,
        off_hours_notice_until=nxt,
    )
    _monitor("ai_off_hours", slot=slot, user_id=user_id, reply_len=len(reply_text))
    return {"ok": True, "reply": reply_text, "off_hours": True, "stage": STAGE_CLOSED}


def _capture_data_room_opportunity(
    slot: str,
    user_id: int,
    *,
    user_text: str,
    history: list[dict] | None,
    lead: dict | None = None,
    qualification: dict | None = None,
) -> None:
    """Save vendor / partnership / support-provider threads to the data room."""
    try:
        # Marketing owns the conversation, while Operations owns Data Room
        # persistence. Emit the bounded opportunity contract instead of
        # importing the Operations store/service into this process.
        from services.opportunity_event_producer import record_from_telegram_thread

        record_from_telegram_thread(
            slot,
            int(user_id),
            user_text=user_text,
            history=history,
            lead=lead,
            qualification=qualification,
        )
    except Exception:
        logger.debug("data_room capture skipped %s %s", slot, user_id, exc_info=True)


async def maybe_schedule_ai_reply(
    slot: str,
    user_id: int,
    *,
    message_id: int | None,
    text: str,
    lead: dict | None,
) -> None:
    """Schedule autonomous AI reply when gates pass.

    Modes:
      - manual / suggest: never enqueue autonomous sends
      - auto: enqueue AI_AUTO_REPLY for background worker execution
    """
    try:
        if not is_enabled():
            _skip_schedule(slot, int(user_id), "ai_disabled")
            return
        if not (text or "").strip():
            _skip_schedule(slot, int(user_id), "empty_text")
            return

        if _inbound_looks_like_outbound_echo(text):
            _skip_schedule(slot, int(user_id), "outbound_echo")
            return

        from core.spam_detector import is_telegram_service_chat

        lead_name = (lead or {}).get("name") or ""
        lead_username = (lead or {}).get("username") or ""
        if is_telegram_service_chat(
            text, name=lead_name, username=lead_username, user_id=int(user_id),
        ):
            _skip_schedule(slot, int(user_id), "telegram_system")
            return

        cfg = get_config()
        mode = (str(cfg.get("mode") or "auto")).strip().lower()
        if mode in {"manual", "suggest"}:
            _skip_schedule(slot, int(user_id), f"mode_{mode}")
            return

        from core.block_store import is_blocked

        if is_blocked(slot, int(user_id)):
            _skip_schedule(slot, int(user_id), "blocked")
            return

        from messaging.account_queue import queue_manager

        if await queue_manager.get_queue(slot).has_pending_ai_auto_reply_for_user(int(user_id)):
            _skip_schedule(slot, int(user_id), "already_queued")
            return

        if _recent_outbound_within_sec(slot, int(user_id), seconds=75):
            _skip_schedule(slot, int(user_id), "recent_outbound")
            return

        if _is_operator_defer_active(slot, int(user_id)):
            _skip_schedule(slot, int(user_id), "operator_deferred")
            return

        # Per-lead override.
        state = get_lead_state(slot, int(user_id))
        state = _karthik_resume_waiting_client(slot, int(user_id), state)
        lock_reason = _human_only_lock_reason(slot, int(user_id), text)
        if lock_reason:
            disable_for_lead(slot, int(user_id), reason=lock_reason)
            _skip_schedule(slot, int(user_id), lock_reason)
            return
        if not state.get("enabled", True):
            _skip_schedule(slot, int(user_id), "lead_ai_disabled")
            return
        disable_reason = (state.get("_disable_reason") or "").strip()
        if state.get("escalated") and disable_reason in _AI_DISABLE_STICKY_REASONS:
            _skip_schedule(slot, int(user_id), "lead_ai_locked")
            return
        if state.get("escalated"):
            if (
                message_id is not None
                and _inbound_still_unanswered(slot, int(user_id), int(message_id))
            ):
                update_lead_state(slot, int(user_id), escalated=False)
                state = get_lead_state(slot, int(user_id))
            else:
                _skip_schedule(slot, int(user_id), "lead_escalated")
                return

        # Already replied to THIS exact incoming message? Don't double-send.
        if message_id and state.get("last_user_message_id") == int(message_id):
            if not _inbound_still_unanswered(slot, int(user_id), int(message_id)):
                _skip_schedule(slot, int(user_id), "already_answered")
                return

        # Block CRM-blocked / spam leads.
        lead_status = (lead or {}).get("status") or ""
        if lead_status in {"spam", "converted", "not_interested"}:
            _skip_schedule(slot, int(user_id), f"lead_{lead_status}")
            return

        # Honour human's pause window — if the operator typed a reply in the
        # last `human_pause_minutes`, the operator is hands-on; AI stays out.
        # Crucially, the AI's own replies also advance `last_reply_at`, so we
        # only pause when the most recent outbound was *actually* from a human.
        last_reply_at = (lead or {}).get("last_reply_at")
        if last_reply_at and _is_last_outbound_human(slot, int(user_id)):
            try:
                last_reply_ts = datetime.fromisoformat(last_reply_at).timestamp()
                pause_min = float(cfg.get("human_pause_minutes", 10))
                if _lead_has_human_owned_thread(slot, int(user_id)):
                    pause_min = max(
                        pause_min,
                        float(os.getenv("AI_HUMAN_OWNED_PAUSE_MINUTES", "1440")),
                    )
                if time.time() - last_reply_ts < pause_min * 60:
                    _skip_schedule(slot, int(user_id), "human_active_pause")
                    return
            except (TypeError, ValueError):
                pass

        # Per-lead daily cap — never block when this inbound is still waiting.
        cap = int(cfg.get("max_replies_per_lead_per_day", 25) or 25)
        at_cap = int(state.get("reply_count_today") or 0) >= cap
        if at_cap:
            still_waiting = (
                message_id is not None
                and _inbound_still_unanswered(slot, int(user_id), int(message_id))
            )
            if not still_waiting:
                _skip_schedule(slot, int(user_id), "daily_cap")
                return

        # Per-account hourly cap.
        acct_cap = int(cfg.get("max_replies_per_account_per_hour", 30) or 30)
        if account_replies_last_hour(slot) >= acct_cap:
            _skip_schedule(slot, int(user_id), "hourly_cap")
            return

        hist = _recent_conversation(slot, int(user_id), limit=12)
        _capture_data_room_opportunity(
            slot,
            int(user_id),
            user_text=text,
            history=hist,
            lead=lead,
        )

        # Enqueue on the account worker so all Telegram I/O for this slot
        # serialises through the existing queue/lock machinery.
        from messaging.message_router import message_router

        _monitor("ai_scheduled", slot=slot, user_id=int(user_id), reason="enqueue")
        await message_router.enqueue_ai_auto_reply(
            slot,
            int(user_id),
            user_message_id=int(message_id) if message_id is not None else None,
            user_text=text,
        )
        logger.info("ai_smart_reply enqueued %s %s msg=%s", slot, user_id, message_id)
    except Exception as e:
        logger.warning("ai_smart_reply schedule %s %s: %s", slot, user_id, e)


AI_REPLY_TIMEOUT_SEC = float(os.getenv("AI_REPLY_TIMEOUT_SEC", "90"))


def _resolve_confidence(ai_out: dict, cfg: dict) -> float:
    """Use model score when present; if it chose to send but omitted score, don't block."""
    try:
        confidence = float(
            ai_out.get("confidence") if ai_out.get("confidence") is not None else 0.0
        )
    except (TypeError, ValueError):
        confidence = 0.0
    reply = (ai_out.get("reply") or "").strip()
    should_send = ai_out.get("should_send", True)
    min_conf = float(cfg.get("min_confidence", 0.45) or 0.45)
    if should_send and reply and confidence < min_conf:
        return max(min_conf, 0.65)
    return confidence


_PRICE_ASK_MARKERS = (
    "price", "charge", "cost", "how much", "entha", "rate", "fee", "amount",
    "pricing", "quotation", "quote", "fees", "charges",
)
_PAYMENT_READY_MARKERS = (
    "how to pay", "payment", "upi", " qr", "book", "proceed", "ready to pay",
    "send payment", "pay cheyy", "payment cheyy", "book cheddam", "confirm slot",
    "ok pay", "okay pay", "will pay", "pay chesta", "pay chey", "gpay", "phonepe",
)


_PAYMENT_READY_MARKERS = (
    "how to pay", "send upi", "send qr", "payment qr", "share upi", "upi id",
    "book cheddam", "book cheyy", "ready to pay", "will pay now", "pay chesta",
    "pay chey", "payment cheyy", "gpay", "phonepe", "pay now", "send payment",
)
_DEFER_MARKERS = (
    "will update", "update u", "update you", "tuesday", "wednesday", "thursday",
    "friday", "monday", "later", "next week", "tomorrow", "ping me", "call chestha",
    "call chey", "call cheddam", "slot confirmation", "after confirm", "think about",
    "let me check", "sare will", "ok will", "okay will", "will let you",
)
_AI_PROBE_MARKERS = (
    "are you ai", "are u ai", "you ai", "human or", "are you human", "are u human",
    "real person", "chatgpt", "automated", "bot aa", "robot", "not human",
)
_NAME_ASK_MARKERS = (
    "your name", "what's your name", "whats your name", "who are you", "who r u",
    "who are u", "may i know your name", "name bro", "name please", "by the your name",
    "tell me your name", "name enti", "peru enti", "name cheppu", "what is your name",
    "good name", "know your name", "introduce yourself", "introduce your", "your good name",
)
_INTRO_COMPLAINT_MARKERS = (
    "hiding", "hidhing", "why you", "why r u", "why are you", "not telling",
    "won't tell", "wont tell", "introduce", "who is this", "who dis",
)


def _user_asks_name(user_text: str) -> bool:
    t = (user_text or "").lower()
    if any(m in t for m in _NAME_ASK_MARKERS):
        return True
    if any(m in t for m in _INTRO_COMPLAINT_MARKERS):
        return True
    # "may i know your good name" / "what name" style
    if "name" in t and any(w in t for w in ("your", "you", "know", "tell", "good", "peru")):
        return True
    return False


def _user_wants_name_in_reply(user_text: str) -> bool:
    return _user_asks_name(user_text) or _user_probes_identity(user_text)


def _is_price_inquiry(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _PRICE_ASK_MARKERS)


_INTEREST_MARKERS = (
    "interested", "i want", "want this", "go ahead", "proceed", "let's do",
    "lets do", "sounds good", "tell me the price", "what's the price",
    "whats the price", "how do i pay", "ready to start", "okay how much",
    "ok how much", "share price", "send price", "want to know the price",
    "price please", "tell price", "share the price", "how much is it",
    "what is the cost", "what's the cost",
)


def _user_asked_price_in_thread(history: list[dict] | None, user_text: str) -> bool:
    if _is_price_inquiry(user_text):
        return True
    for m in (history or []):
        if m.get("role") == "user" and _is_price_inquiry(m.get("content") or ""):
            return True
    return False


def _user_shows_purchase_interest(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in _INTEREST_MARKERS)


def _assistant_offered_process_or_pricing(history: list[dict] | None) -> bool:
    last = (_last_assistant_text(history) or "").lower()
    return "process" in last and "pricing" in last


def _user_affirms_process_or_pricing(user_text: str, history: list[dict] | None) -> bool:
    t = (user_text or "").strip().lower()
    if t in ("yes", "yeah", "yep", "sure", "ok", "okay", "both", "yes both", "both please"):
        return _assistant_offered_process_or_pricing(history)
    if t == "both" and _assistant_offered_process_or_pricing(history):
        return True
    return False


def _process_and_pricing_reply(
    facts: dict,
    *,
    lang: str,
    lead: dict | None,
) -> str:
    """After user says yes/both to process-or-pricing question."""
    addr = _addr_prefix(lead, lang)
    tech = (facts.get("tech_stack") or "").strip()
    tech_bit = f" for your {tech} round" if tech else ""
    if lang == "english":
        return (
            f"Got it {addr}👍 Demo first, then live round help{tech_bit}. "
            f"₹5000/round India. Client or technical?"
        )
    return (
        f"Got it {addr}👍 Demo first, tarvata live support{tech_bit}. "
        f"₹5000/round India. Client aa technical aa?"
    )


def _should_quote_price(
    user_text: str,
    history: list[dict] | None = None,
    qualification: dict | None = None,
) -> bool:
    """Price only when user asked or shows clear buy interest.

    Karthik never quotes amounts on Power BI / data-analyst leads — hand off to Vani.
    """
    if history is not None and _is_data_analyst_domain(history, user_text, qualification):
        return False
    return _user_asked_price_in_thread(history, user_text) or _user_shows_purchase_interest(user_text)


def _reply_has_pricing(reply_text: str) -> bool:
    t = reply_text or ""
    lower = t.lower()
    if "₹" in t or "rs." in lower or " rupees" in lower:
        return True
    if any(x in lower for x in (" lakhs", " lakh", "1.8l", "1.8 l")):
        return True
    import re
    if re.search(r"\b\d+k\b", lower):
        return True
    if re.search(r"\b\d{1,3},?\d{3}\b", t):
        return True
    return False


def _user_ready_for_payment(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in _PAYMENT_READY_MARKERS)


def _user_deferred(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in _DEFER_MARKERS)


def _user_probes_identity(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in _AI_PROBE_MARKERS)


_SMALL_TALK_MARKERS = (
    "how are you", "how r u", "how are u", "how's you", "hows you", "how is you",
    "how do you do", "how're you", "how re you", "all well", "you didn't reply",
    "you didnt reply", "didn't reply", "didnt reply", "how's it going", "hows it going",
    "good morning", "good evening", "good afternoon",
)
_PERSONAL_QUESTION_MARKERS = (
    "studying in", "study in", "where are you", "where do you live", "where do you stay",
    "which city", "melbourne", "sydney", "from where", "your age", "how old are",
    "are you in", "do you live", "which college", "which university", "which country",
    "are you from", "where r u", "where are u",
)
_CONFUSION_MARKERS = (
    "what do you mean", "didn't understand", "dont understand", "don't understand",
    "confused", "not understand", "what r u saying", "what are you saying",
)
_FEMININE_FIRST_NAMES = frozenset({
    "anjali", "priya", "sneha", "kavya", "divya", "swathi", "swati", "lakshmi",
    "pooja", "neha", "shreya", "aishwarya", "deepika", "meera", "nisha", "revathi",
    "charulata", "bhavana", "nikhila", "jhansi", "triveni", "hemalatha", "srujana",
    "sathvika",
})
_LOOP_REPLY_MARKERS = (
    "we were already chatting", "let's continue from there", "continue from there",
    "let me know if you need anything else", "if you have any other questions",
    "interview support, resume help, or naukri",
    "ready to discuss further", "ping me anytime when you're ready",
)
_CLOSING_REPLY_MARKERS = (
    "let me know if you need", "if you need anything else", "any other questions",
    "need assistance later", "ping me anytime", "no problem",
)


_IMPERSONAL_LEAD_NAMES = frozenset({
    "codex", "giguyz", "services", "support", "llp", "interview", "admin",
    "user", "telegram", "unknown", "customer", "client", "team",
})


def _is_impersonal_lead_name(name: str) -> bool:
    """Company/chat titles — not a person's first name."""
    n = (name or "").strip().lower()
    if not n:
        return True
    first = n.split()[0]
    if first in _IMPERSONAL_LEAD_NAMES:
        return True
    if any(w in n for w in (" llp", " services", " support", " pvt", " ltd", " company")):
        return True
    return False


def _first_name(lead: dict | None) -> str:
    """Client first name from lead/inbox — empty if unknown."""
    raw = (lead.get("name") or "").strip() if lead else ""
    if not raw or _is_impersonal_lead_name(raw):
        return ""
    first = raw.split()[0]
    if first.startswith("@") or first.replace("_", "").isdigit():
        return ""
    if _is_impersonal_lead_name(first):
        return ""
    if len(first) == 1:
        return first.upper()
    return first[0].upper() + first[1:]


def _enrich_lead_with_inbox_name(slot: str, user_id: int, lead: dict | None) -> dict:
    """Fill missing lead name/username from inbox conversation metadata."""
    lead = dict(lead or {})
    if _first_name(lead):
        return lead
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    name = (conv.get("name") or "").strip()
    if name:
        lead["name"] = name
    if not (lead.get("username") or "").strip():
        un = (conv.get("username") or "").strip().lstrip("@")
        if un:
            lead["username"] = un
    return lead


def _friendly_address(lead: dict | None, lang: str = "english") -> str:
    """Use client first name when known — never 'bro'."""
    return _first_name(lead)


def _assistant_reply_count(history: list[dict] | None) -> int:
    return sum(
        1 for m in (history or [])
        if (m.get("role") or "").lower() == "assistant"
    )


def _reply_ack_prefix(
    lead: dict | None,
    lang: str = "english",
    *,
    history: list[dict] | None = None,
) -> str:
    """Rotate ack openers — avoid starting every chat with 'Got it'."""
    name = _first_name(lead)
    slot = _assistant_reply_count(history) % 4
    if lang == "english":
        patterns = (
            ("Okay", f"Okay {name} 👍 " if name else "Okay 👍 "),
            ("Sure", f"Sure {name} 👍 " if name else "Sure 👍 "),
            ("Noted", f"Noted {name} 👍 " if name else "Noted 👍 "),
            ("Yes", f"Yes {name} 👍 " if name else "Yes 👍 "),
        )
    else:
        patterns = (
            ("Okay", f"Okay {name} 👍 " if name else "Okay 👍 "),
            ("Sure", f"Sure {name} 👍 " if name else "Sure 👍 "),
            ("Avunu", f"Avunu {name} 👍 " if name else "Avunu 👍 "),
            ("Yes", f"Yes {name} 👍 " if name else "Yes 👍 "),
        )
    return patterns[slot][1]


def _got_it_prefix(
    lead: dict | None,
    lang: str = "english",
    *,
    history: list[dict] | None = None,
) -> str:
    return _reply_ack_prefix(lead, lang, history=history)


def _vary_got_it_opener(text: str, history: list[dict] | None) -> str:
    """Never lead with 'Got it' — mobile previews looked identical across chats."""
    s = (text or "").strip()
    if not s or not s.lower().startswith("got it"):
        return s
    alts = ("Okay", "Sure", "Noted", "Yes")
    alt = alts[_assistant_reply_count(history) % len(alts)]
    return re.sub(r"(?i)^got it\s*", f"{alt} ", s, count=1)


def _okay_prefix(lead: dict | None, lang: str = "english") -> str:
    name = _first_name(lead)
    if name:
        return f"Okay {name} 👍 "
    return "Okay 👍 "


def _sorry_prefix(lead: dict | None, *, confusion: bool = False) -> str:
    name = _first_name(lead)
    if confusion:
        if name:
            return f"Sorry for the confusion {name} 👍 "
        return "Sorry for the confusion 👍 "
    if name:
        return f"Sorry {name} my bad 👍 "
    return "Sorry my bad 👍 "


def _enforce_name_not_bro(text: str, lead: dict | None, lang: str = "english") -> str:
    """Replace casual 'bro' with the client's first name, or remove it."""
    if not text or "bro" not in text.lower():
        return text
    name = _first_name(lead)
    if name:
        subs: list[tuple[str, str]] = [
            (r"(?i)\bGot it bro,\s*", f"Got it {name}, "),
            (r"(?i)\bGot it bro\b", f"Got it {name}"),
            (r"(?i)\bOkay bro\b", f"Okay {name}"),
            (r"(?i)\bSure bro,\s*", f"Sure {name}, "),
            (r"(?i)\bSure bro\b", f"Sure {name}"),
            (r"(?i)\bSorry bro my bad\b", f"Sorry {name} my bad"),
            (r"(?i)\bSorry for confusion bro\b", f"Sorry for the confusion {name}"),
            (r"(?i)\bSorry for the confusion bro\b", f"Sorry for the confusion {name}"),
            (r"(?i)\bHaha no bro\b", f"Haha no {name}"),
            (r"(?i)\bno bro\b", f"no {name}"),
            (r"(?i)\bI'm Karthik bro\b", f"I'm Karthik, {name}"),
            (r"(?i)\bLakhs bro\b", f"Lakhs {name}"),
            (r"(?i)\bAny updates bro\b", f"Any updates {name}"),
            (r"(?i)\bbro 👍", f"{name} 👍"),
            (r"(?i)\bbro,", f"{name},"),
            (r"(?i)\sbro\b", f" {name}"),
        ]
    else:
        subs = [
            (r"(?i)\bGot it bro,\s*", "Got it, "),
            (r"(?i)\bGot it bro\b", "Got it"),
            (r"(?i)\bOkay bro\b", "Okay"),
            (r"(?i)\bSure bro,\s*", "Sure, "),
            (r"(?i)\bSure bro\b", "Sure"),
            (r"(?i)\bSorry bro my bad\b", "Sorry my bad"),
            (r"(?i)\bSorry for confusion bro\b", "Sorry for the confusion"),
            (r"(?i)\bSorry for the confusion bro\b", "Sorry for the confusion"),
            (r"(?i)\bHaha no bro\b", "Haha no"),
            (r"(?i)\bno bro\b", "no"),
            (r"(?i)\bI'm Karthik bro\b", "I'm Karthik"),
            (r"(?i)\bLakhs bro\b", "Lakhs"),
            (r"(?i)\bAny updates bro\b", "Any updates"),
            (r"(?i)\bbro 👍", "👍"),
            (r"(?i)\bbro,", ","),
            (r"(?i)\sbro\b", ""),
        ]
    out = text
    for pat, repl in subs:
        out = re.sub(pat, repl, out)
    out = re.sub(r"  +", " ", out)
    out = re.sub(r"👍\s+👍", "👍", out)
    out = re.sub(r",\s*,", ",", out)
    return out.strip()


def _addr_prefix(lead: dict | None, lang: str) -> str:
    a = _friendly_address(lead, lang)
    return f"{a} " if a else ""


def _user_small_talk(user_text: str) -> bool:
    t = (user_text or "").lower().strip()
    if t in ("ok", "okay", "k", "👍"):
        return False
    if t in ("hi", "hello", "hey", "hii", "hello 👋"):
        return True
    return any(m in t for m in _SMALL_TALK_MARKERS)


def _user_personal_question(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in _PERSONAL_QUESTION_MARKERS)


def _user_confused(user_text: str) -> bool:
    t = (user_text or "").lower().strip().rstrip("?!.")
    return t in ("what", "huh", "ok what", "what what") or any(m in t for m in _CONFUSION_MARKERS)


def _last_assistant_text(history: list[dict] | None) -> str:
    for m in reversed(history or []):
        if m.get("role") == "assistant":
            return (m.get("content") or "").strip()
    return ""


def _is_loop_reply(reply_text: str) -> bool:
    lower = (reply_text or "").lower()
    return any(m in lower for m in _LOOP_REPLY_MARKERS)


def _assistant_recently_said(history: list[dict] | None, reply_text: str) -> bool:
    target = (reply_text or "").strip().lower()
    if not target:
        return False
    count = 0
    for m in reversed(history or []):
        if m.get("role") != "assistant":
            continue
        if (m.get("content") or "").strip().lower() == target:
            return True
        if _replies_too_similar(m.get("content") or "", reply_text):
            return True
        count += 1
        if count >= 3:
            break
    return False


def _user_short_decline(user_text: str) -> bool:
    t = (user_text or "").lower().strip().rstrip("!.,")
    return t in (
        "no", "noo", "nope", "nah", "not really", "nothing", "no thanks",
        "no thank you", "not interested", "not now",
    )


def _proctor_exam_markers() -> tuple[str, ...]:
    return globals().get("_PROCTOR_EXAM_MARKERS") or ()


def _user_asks_proctoring(user_text: str, history: list[dict] | None) -> bool:
    blob = _conversation_blob(history or [], user_text or "", tail=16)
    if any(m in blob for m in _proctor_exam_markers()):
        return True
    return "proct" in blob


def _proctoring_service_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    en = lang == "english"
    addr = _addr_prefix(lead, lang)
    if _user_short_decline(user_text):
        if en:
            return f"Got it {addr}👍 ping me anytime if you need exam or proctor support."
        return f"Got it {addr}👍 exam/proctor support kavali ante ping cheyyandi 👍"
    if en:
        return (
            f"Got it {addr}👍 we help with online exam / proctoring support. "
            f"Please share a screenshot of your exam invite or scheduling page here 👍"
        )
    return (
        f"Got it {addr}👍 online exam / proctoring support help chestham. "
        f"Exam invite or schedule screenshot share cheyyandi 👍"
    )


def _get_recent_outbound_texts(slot: str, user_id: int, *, limit: int = 3) -> list[str]:
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    texts: list[str] = []
    for m in reversed(conv.get("messages") or []):
        if m.get("direction") != "out":
            continue
        text = (m.get("text") or "").strip()
        if text:
            texts.append(text)
        if len(texts) >= limit:
            break
    return texts


def _replies_too_similar(a: str, b: str) -> bool:
    na = re.sub(r"\s+", " ", (a or "").lower().strip())
    nb = re.sub(r"\s+", " ", (b or "").lower().strip())
    if not na or not nb:
        return False
    if na == nb:
        return True
    if any(m in na and m in nb for m in _CLOSING_REPLY_MARKERS):
        return True
    words_a = set(na.split())
    words_b = set(nb.split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b) / len(words_a | words_b)
    return overlap >= 0.62


def _duplicate_outbound_blocked(slot: str, user_id: int, reply_text: str) -> bool:
    for recent in _get_recent_outbound_texts(slot, user_id, limit=3):
        if _replies_too_similar(recent, reply_text):
            return True
    return False


def _recent_outbound_within_sec(slot: str, user_id: int, seconds: float = 90) -> bool:
    """Block back-to-back AI sends to the same lead (catch-up / retry storms)."""
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    msgs = conv.get("messages") or []
    for m in reversed(msgs):
        if m.get("direction") != "out":
            continue
        ts = m.get("created_at") or m.get("timestamp") or conv.get("last_message_at")
        if not ts:
            return False
        try:
            age = time.time() - datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
            return age < seconds
        except (TypeError, ValueError):
            return False
    return False


def _inbound_looks_like_outbound_echo(text: str) -> bool:
    """Skip when sync echoed our own outbound as inbound (prevents reply loops)."""
    t = (text or "").strip()
    if not t:
        return False
    lower = t.lower()
    if lower.startswith("got it ") and "👍" in t[:50]:
        return True
    if "interview support, resume help" in lower or "resume help, or naukri" in lower:
        return True
    if lower.startswith("yes ") and "👍" in t[:30] and ("📞" in t or "wa.me" in lower):
        return True
    return False


def _deterministic_reply_fallback(
    user_text: str,
    cfg: dict,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lead: dict | None,
) -> str:
    """Rule-based reply when LLM escalates / low confidence — never return generic menu."""
    out = _humanize_reply(
        "", user_text, cfg, history=history, qualification=qualification, lead=lead,
    )
    if out.strip() and not _looks_generic_assistant(out):
        return out
    known = _known_facts_for_reply(history, qualification, user_text)
    if known.get("tech_stack") or known.get("service_need"):
        contextual = _reply_from_known_facts(
            known,
            lang=_detect_client_language(history, user_text),
            history=history,
            user_text=user_text,
        )
        if contextual:
            return contextual
    return ""


def _is_llm_transient_error(exc: BaseException) -> bool:
    """Rate limits, overload, or timeouts — use rule-based fallback instead of silence."""
    msg = f"{type(exc).__name__} {exc!r} {exc}".lower()
    if any(
        token in msg
        for token in (
            "429",
            "too many requests",
            "rate limit",
            "rate_limit",
            "503",
            "502",
            "service unavailable",
            "overloaded",
            "timeout",
            "timed out",
        )
    ):
        return True
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if code in (429, 502, 503):
            return True
    return False


def _is_llm_rate_limited(exc: BaseException) -> bool:
    msg = f"{exc!r} {exc}".lower()
    if "429" in msg or "too many requests" in msg or "rate limit" in msg:
        return True
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 429


def _inbound_looks_like_external_recruitment(
    user_text: str,
    history: list[dict] | None,
) -> bool:
    """Field hiring / bulk candidate drives — not interview-support seekers."""
    blob = _user_only_blob(history, user_text, tail=12)
    markers = (
        "recruitment",
        "candidates kosam",
        "google pixel",
        "aadhaar card",
        "travel allowance",
        "field work",
        "candidates required",
        "looking for candidates",
        "we need candidates",
        "requirement",
        "interested candidates",
        "share your aadhaar",
    )
    hits = sum(1 for m in markers if m in blob)
    if hits >= 2:
        return True
    return "recruitment" in blob and any(
        w in blob for w in ("candidates", "aadhaar", "requirement", "pixel")
    )


def _external_recruitment_reply(
    *,
    lang: str,
    lead: dict | None,
) -> str:
    addr = _addr_prefix(lead, lang)
    if lang == "english":
        return (
            f"Hi {addr}👍 Thanks — this looks like a field hiring / recruitment post, "
            f"not our interview-support line. We are not hiring for that project 👍"
        )
    return (
        f"Hi {addr}👍 Message chusanu — idi field hiring/recruitment post; "
        f"memu interview support team. Ee project ki candidates avasaram ledu 👍"
    )


def _reply_fallback_for_llm_outage(
    user_text: str,
    cfg: dict,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lead: dict | None,
    rate_limited: bool = False,
) -> str:
    """Rule-based reply when OpenAI (or gateway) is unavailable."""
    out = _deterministic_reply_fallback(
        user_text, cfg, history=history, qualification=qualification, lead=lead,
    )
    if out.strip():
        return out.strip()

    lang = _detect_client_language(history, user_text)
    addr = _addr_prefix(lead, lang)
    assistant = (cfg.get("assistant_name") or "").strip() or "Karthik"
    en = lang == "english"
    qual = qualification or {}

    social = _social_context_reply(
        user_text, history=history, lang=lang, lead=lead, assistant_name=assistant,
    )
    if social.strip():
        return social.strip()

    if _user_asks_backdoor_jobs(user_text, history):
        return _backdoor_jobs_reply(user_text, history=history, lang=lang, lead=lead)

    if _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history):
        return _vendor_partner_reply(
            user_text, history=history, qualification=qual, lang=lang, lead=lead,
        )

    if _job_support_thread_closed(user_text, history):
        return _job_support_closed_ack(lang, lead)
    if _user_requests_india_job_support(user_text, history):
        return _india_no_job_support_reply(lang=lang, lead=lead)
    if _inbound_looks_like_external_recruitment(user_text, history):
        return _external_recruitment_reply(lang=lang, lead=lead)

    if rate_limited:
        intent = resolve_thread_intent(history, user_text, qual)
        if intent in (INTENT_INTERVIEW, INTENT_INTERVIEW_TILL_OFFER, INTENT_PROXY):
            if en:
                return (
                    f"Hi {addr}👍 Got your message — replies are a bit slow on my side right now. "
                    f"Which tech stack is your interview in?"
                )
            return (
                f"Hi {addr}👍 Message chusanu — ippudu replies slow ga vastunnayi. "
                f"Interview ki em tech stack?"
            )
        if en:
            return (
                f"Hi {addr}👍 Got your message — replies are a bit slow on my side right now. "
                f"I'll follow up shortly 👍"
            )
        return (
            f"Hi {addr}👍 Message chusanu — ippudu replies slow ga vastunnayi. "
            f"Konchem aithe follow-up chestha 👍"
        )

    if en:
        return (
            f"Hi {addr}👍 I'm {assistant}. What can I help you with — "
            f"interview support, resume, or Naukri?"
        )
    return (
        f"Hi {addr}👍 nenu {assistant}. Interview support, resume, leda Naukri — em help kavali?"
    )


def _social_context_reply(
    user_text: str,
    *,
    history: list[dict] | None,
    lang: str,
    lead: dict | None,
    assistant_name: str,
) -> str:
    """Handle greetings, small talk, personal questions, confusion — never loop."""
    if _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history):
        if _user_small_talk(user_text) or _user_confused(user_text):
            return _vendor_partner_reply(
                user_text, history=history, lang=lang, lead=lead, small_talk=_user_small_talk(user_text),
            )

    en = lang == "english"
    addr = _addr_prefix(lead, lang)
    t = (user_text or "").lower()

    if _user_confused(user_text):
        last = _last_assistant_text(history)
        if _is_loop_reply(last) or not last:
            if en:
                return (
                    f"Sorry {addr}my bad — I'm {assistant_name} from the interview support team. "
                    f"Are you looking for interview help, resume, or Naukri support?"
                )
            return (
                f"Sorry {addr}my bad — nenu {assistant_name}, interview support team nundi. "
                f"Interview help, resume, leda Naukri support kavala?"
            )
        if en:
            return f"Sorry {addr}let me be clear — I'm {assistant_name} from the team. What help do you need?"
        return f"Sorry {addr}clear ga cheptanu — nenu {assistant_name}, team nundi. Em help kavali?"

    if _user_personal_question(user_text):
        if en:
            return (
                f"Haha no {addr}😄 I'm {assistant_name} from our team in India — "
                f"we help with interviews & resume in India; job support only non-domestic. "
                f"What are you looking for?"
            )
        return (
            f"Haha ledu {addr}😄 nenu {assistant_name}, India lo team nundi — "
            f"interview & resume; job support abroad matrame. Em kavali meeku?"
        )

    if any(m in t for m in ("didn't reply", "didnt reply", "you didn't reply", "all well")):
        if en:
            return (
                f"Sorry for the late reply {addr}👍 I'm {assistant_name} — all good here. "
                f"What can I help you with — interview, resume, or Naukri?"
            )
        return (
            f"Sorry late ayyindi {addr}👍 nenu {assistant_name} — all good. "
            f"Em help kavali — interview, resume, leda Naukri?"
        )

    if _user_small_talk(user_text):
        if t in ("hi", "hello", "hey", "hii", "hello 👋", "hey 👋"):
            if en:
                return f"Hi {addr}👍 I'm {assistant_name}. What can I help you with?"
            return f"Hi {addr}👍 nenu {assistant_name}. Em help kavali?"
        if en:
            return (
                f"All good {addr}👍 thanks! I'm {assistant_name}. "
                f"What can I help you with?"
            )
        return (
            f"All good {addr}👍 thanks! Nenu {assistant_name}. "
            f"Em help kavali?"
        )

    return ""


_CHAT_REFUSAL_MARKERS = (
    "can't chat", "cannot chat", "i can't chat", "cant chat", "won't chat", "sorry i can't chat",
)
_CALL_REQUEST_MARKERS = (
    "want to call", "want a call", "need a call", "phone support", "need phone",
    "discuss in call", "discuss on call",
    "discuss over call", "talk on call", "speak on call", "connect on call", "call you",
    "phone call", "voice call", "could we connect", "can we connect", "connect now",
    "discuss in a call", "schedule a call", "book a call", "on a call", "over a call",
    "want to discuss in call", "discuss in phone", "call discussion", "discuss in call",
    "connect here", "connect with you", "speak with you", "talk with you",
    "available for call", "available for a call", "are you available for call",
    "ping me in whatsapp", "ping me on whatsapp", "ping on whatsapp", "ping me whatsapp",
    "whatsapp me", "on whatsapp", "in whatsapp", "reach me on whatsapp",
)
_WHATSAPP_REQUEST_MARKERS = (
    "whatsapp", "whats app", "wa.me", "ping me in whatsapp", "ping me on whatsapp",
    "ping on whatsapp", "ping me whatsapp", "whatsapp me", "on whatsapp", "in whatsapp",
)
_OFFLINE_AUTO_MARKERS = (
    "currently offline", "reply in working hours", "working hours",
)
_CANT_TAKE_CALL_MARKERS = (
    "can't take calls", "cannot take calls", "can't take call", "cannot take call",
    "i can't call", "help you through chat", "can't do calls", "cannot do calls",
    "unable to take calls", "not able to take calls", "i can't take calls",
)


def _user_refuses_chat(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in _CHAT_REFUSAL_MARKERS)


def _offline_online_markers() -> tuple[str, ...]:
    return globals().get("_OFFLINE_ONLINE_MARKERS") or ()


def _offline_denial_markers() -> tuple[str, ...]:
    return globals().get("_OFFLINE_DENIAL_MARKERS") or ()


def _user_asks_offline_online(user_text: str, history: list[dict] | None = None) -> bool:
    """User asks about offline vs online / in-person support."""
    t = (user_text or "").lower()
    if any(m in t for m in _offline_online_markers()):
        return True
    if "offline" in t and "online" in t:
        return True
    blob = _conversation_blob(history or [], user_text, tail=12)
    if "offline" in blob and any(w in blob for w in ("online", "or online", "vs online", "office visit")):
        return True
    return False


def _reply_denies_offline(reply_text: str) -> bool:
    lower = (reply_text or "").lower()
    return any(m in lower for m in _offline_denial_markers())


def _offline_online_support_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Offline + online support both available — never online-only denial."""
    en = lang == "english"
    addr = _addr_prefix(lead, lang)
    t = (user_text or "").lower()
    blob = _conversation_blob(history or [], user_text, tail=12)
    wants_offline = (
        "offline" in t
        or any(w in blob for w in ("offline support", "office visit", "in person", "in-person", "on site", "on-site"))
    )
    if wants_offline:
        if en:
            return f"Yes {addr}👍 offline support is available. Which city are you in?"
        return f"Yes {addr}👍 offline support kuda untundi. Meeru e city?"
    if en:
        return (
            f"Got it {addr}👍 we do both online and offline support — "
            f"depends on your need and city. Which one do you prefer?"
        )
    return (
        f"Got it {addr}👍 online & offline rendu support untundi — "
        f"meeku edi kavali?"
    )


def _user_wants_whatsapp(user_text: str, history: list[dict] | None = None) -> bool:
    blob = _conversation_blob(history or [], user_text or "", tail=16)
    return any(m in blob for m in _WHATSAPP_REQUEST_MARKERS)


def _user_shared_phone(user_text: str, history: list[dict] | None = None) -> bool:
    blob = _conversation_blob(history or [], user_text or "", tail=12)
    return bool(re.search(r"\b\d{10}\b", blob))


def _active_call_whatsapp_thread(history: list[dict] | None, user_text: str = "") -> bool:
    """Ongoing call / WhatsApp coordination — never drop offline auto-replies here."""
    blob = _conversation_blob(history or [], user_text or "", tail=24)
    if _user_wants_whatsapp(user_text, history) or _user_wants_phone_call(user_text, history):
        return True
    if _user_shared_phone(user_text, history) and any(
        w in blob for w in ("call", "whatsapp", "available", "ping", "now", "number")
    ):
        return True
    if any(m in blob for m in (
        "available for call", "available for a call", "give me two minutes",
        "two minutes please", "ping me in whatsapp", "ping me on whatsapp",
    )):
        return True
    return False


def _user_short_ack(user_text: str) -> bool:
    t = (user_text or "").lower().strip().rstrip("!.,")
    return t in ("ok", "okay", "okay fine", "ok fine", "fine", "k", "sure", "yes")


def _user_wants_phone_call(user_text: str, history: list[dict] | None = None) -> bool:
    """User wants a voice/call connect — NOT 'not getting calls' from Naukri."""
    t = (user_text or "").lower().strip()
    if _user_wants_whatsapp(user_text, history):
        return True
    if any(p in t for p in (
        "call me", "you can call me", "you can call", "call me back",
        "please call me", "can you call me", "can u call me", "call me when",
        "can i call", "can we call", "may i call", "i want to call",
        "available for call", "available for a call", "are you available for call",
        "phone support", "need phone",
    )):
        return True
    blob = _conversation_blob(history or [], user_text, tail=8)
    if any(m in blob for m in _AUTOMATION_CALL_MARKERS):
        return False
    if "not getting call" in blob or "calls aren't coming" in blob or "no calls from" in blob:
        return False
    if _user_shared_phone(user_text, history) and any(
        w in blob for w in ("call", "whatsapp", "available", "now", "ping")
    ):
        return True
    if any(m in blob for m in ("call later", "call chestha", "call chey", "call cheddam")):
        if not any(m in blob for m in _CALL_REQUEST_MARKERS):
            return False
    if "ping me" in blob and not any(m in blob for m in _WHATSAPP_REQUEST_MARKERS):
        if not any(m in blob for m in _CALL_REQUEST_MARKERS):
            return False
    if any(m in blob for m in _CALL_REQUEST_MARKERS):
        return True
    if "connect" in blob and any(w in blob for w in ("call", "discuss", "phone", "speak", "talk")):
        return True
    return False


def _call_senior_contact(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None,
    *,
    lang: str = "english",
) -> str:
    """Senior phone + WhatsApp for call requests — routed by role."""
    en = lang == "english"
    garu = "" if en else " garu"
    if _is_data_analyst_domain(history, user_text, qualification):
        return f"Vani{garu} (senior data analyst) 📞 {VANI_PHONE} 📲 {VANI_WHATSAPP}"
    if _is_devops_domain(history, user_text, qualification):
        return f"Kalyan{garu} (senior) 📞 {KALYAN_PHONE} 📲 {KALYAN_WHATSAPP}"
    if _is_react_frontend_domain(history, user_text, qualification):
        return (
            f"Nikhila{garu} 📞 {NIKHILA_PHONE} 📲 {NIKHILA_WHATSAPP} | "
            f"Bhavana{garu} 📞 {BHAVANA_PHONE} 📲 {BHAVANA_WHATSAPP}"
        )
    return f"Thirlok{garu} (senior) 📞 {THRILOK_PHONE} 📲 {THRILOK_WHATSAPP}"


def _call_senior_phone_only(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None,
    *,
    lang: str = "english",
) -> str:
    """Digits-only phone for short call handoffs."""
    contact = _call_senior_contact(history, user_text, qualification, lang=lang)
    m = re.search(r"📞\s*([+\d\s]+)", contact)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return THRILOK_PHONE


def _call_senior_name(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None,
    *,
    lang: str = "english",
) -> str:
    contact = _call_senior_contact(history, user_text, qualification, lang=lang)
    name = (contact.split("(")[0].split("📞")[0].strip() or "Thirlok").split("|")[0].strip()
    return name or "Thirlok"


MAX_REPLY_CHARS = 180
MAX_REPLY_LINES = 2
MAX_REPLY_WORDS = 32


def _enforce_short_reply(text: str) -> str:
    """Concise WhatsApp replies — necessary info only, no filler."""
    s = (text or "").strip()
    if not s:
        return ""
    # Drop markdown bullets / numbered lists (models ignore "no bullets" often).
    s = re.sub(r"(?m)^\s*[-*•]\s+", "", s)
    s = re.sub(r"(?m)^\s*\d+[.)]\s+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # One question max.
    if s.count("?") > 1:
        q = s.find("?")
        if q > 0:
            s = s[: q + 1].strip()
    words = s.split()
    if len(words) > MAX_REPLY_WORDS:
        s = " ".join(words[:MAX_REPLY_WORDS]).rstrip(" ,;—-")
        for sep in (". ", "? ", "! "):
            idx = s.rfind(sep)
            if idx > 40:
                s = s[: idx + 1].strip()
                break
    lines = [ln.strip() for ln in re.split(r"\n+", s) if ln.strip()]
    if len(lines) > MAX_REPLY_LINES:
        lines = lines[:MAX_REPLY_LINES]
        s = "\n".join(lines)
    if len(s) <= MAX_REPLY_CHARS:
        return s
    cut = s[:MAX_REPLY_CHARS]
    for sep in (". ", "? ", "! ", " — ", " - "):
        idx = cut.rfind(sep)
        if idx > 50:
            return cut[: idx + len(sep.rstrip())].strip()
    return cut.rstrip(" ,;—-") + "…"


def _tech_team_demo_phrase(lang: str) -> str:
    """How we explain interview support — demo first, not live call/WhatsApp detail."""
    if lang == "english":
        return "our tech team will give you a demo first"
    return "tech team mundu demo istharu"


def _tech_team_demo_phrase_short(lang: str) -> str:
    if lang == "english":
        return "tech team will give you a demo"
    return "tech team demo istharu"


def _vendor_call_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Short call yes for vendor/partnership threads."""
    en = lang == "english"
    addr = _addr_prefix(lead, lang)
    phone = _call_senior_phone_only(history, user_text, qualification, lang=lang)
    senior = _call_senior_name(history, user_text, qualification, lang=lang)
    if en:
        return f"Yes {addr}👍 {senior} (senior) will call you 📞 {phone}"
    return f"Yes {addr}👍 {senior} (senior) call chestharu 📞 {phone}"


def _call_handoff_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
    empathy: bool = False,
) -> str:
    """Share senior team contacts when user wants a call — never say 'can't take calls'."""
    en = lang == "english"
    addr = _addr_prefix(lead, lang)
    contact = _call_senior_contact(history, user_text, qualification, lang=lang)
    wants_wa = _user_wants_whatsapp(user_text, history) or _user_wants_whatsapp("", history)
    if _user_refuses_chat(user_text):
        if en:
            return f"No problem {addr}👍 our senior team will help — {contact}"
        return f"No problem {addr}👍 senior team help chestharu — {contact}"
    if wants_wa:
        if en:
            return f"Yes {addr}👍 {contact} — ping on WhatsApp or call anytime."
        return f"Yes {addr}👍 {contact} — WhatsApp lo ping cheyyandi leda call cheyyandi."
    if en:
        return f"Yes {addr}👍 {contact}"
    return f"Yes {addr}👍 {contact}"


def _enforce_call_handoff(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Replace 'can't take calls' with senior contact handoff."""
    lower = (reply_text or "").lower()
    wants_call = _user_wants_phone_call(user_text, history) or _user_refuses_chat(user_text)
    bad = any(m in lower for m in _CANT_TAKE_CALL_MARKERS)
    if wants_call or bad:
        return _call_handoff_reply(
            user_text, history=history, qualification=qualification,
            lang=lang, lead=lead, empathy=_user_refuses_chat(user_text),
        )
    return reply_text


def _qualify_soft_opener(lang: str, lead: dict | None) -> str:
    addr = _addr_prefix(lead, lang)
    if lang == "english":
        return f"Got it {addr}👍 are you looking for interview support, resume help, or Naukri help?"
    return f"Got it {addr}👍 interview support, resume, leda Naukri help kavala?"


def _intent_continuation_reply(
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Contextual reply from locked thread intent — never reset to generic menu."""
    qual = qualification or {}
    intent = resolve_thread_intent(history, user_text, qual)
    known = _known_facts_for_reply(history, qual, user_text)

    if intent in (INTENT_INTERVIEW, INTENT_INTERVIEW_TILL_OFFER, INTENT_PROXY):
        t = (user_text or "").lower()
        if any(m in t for m in ("recording", "listen to", "voice sample", "sample call", "hear them", "listed their")):
            return _interview_support_smart_reply(
                known, history=history, user_text=user_text,
                qualification=qual, lang=lang, lead=lead,
            )
        if _interview_fully_qualified(known, history, user_text):
            return _interview_support_smart_reply(
                known, history=history, user_text=user_text,
                qualification=qual, lang=lang, lead=lead,
            )
        contextual = _reply_from_known_facts(
            known, lang=lang, history=history, user_text=user_text,
        )
        if contextual:
            return contextual

    if intent == INTENT_JOB_SEARCH:
        return _job_search_service_reply(
            history, user_text, lang=lang,
            include_price=_should_quote_price(user_text, history),
        )

    if intent == INTENT_DEV_COLLAB:
        return _dev_collaboration_reply(user_text, history=history, lang=lang, lead=lead)

    hook = _thread_continuation(history or [], qual, user_text, lang)
    if hook:
        return hook

    if known.get("tech_stack") or known.get("service_need"):
        contextual = _reply_from_known_facts(
            known, lang=lang, history=history, user_text=user_text,
        )
        if contextual:
            return contextual

    return _qualify_soft_opener(lang, lead)


def _enforce_thread_intent_coherence(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Block wrong-funnel replies when thread intent is locked."""
    qual = qualification or {}
    intent = resolve_thread_intent(history, user_text, qual)
    lower = (reply_text or "").lower()

    wrong_funnel = False
    if intent_blocks_job_search(intent) and _reply_looks_like_naukri_pitch(reply_text):
        wrong_funnel = True
    if intent_blocks_dev_collab(intent) and (
        "dev collaboration" in lower
        or "freelance dev" in lower
        or "great developer for your build" in lower
        or "not available for dev collaboration" in lower
    ):
        wrong_funnel = True
    if intent_blocks_generic_menu(intent, qual) and (
        _looks_generic_assistant(reply_text) or "resume help, or naukri" in lower
    ):
        wrong_funnel = True

    if not wrong_funnel:
        return reply_text

    return _intent_continuation_reply(
        user_text, history=history, qualification=qual, lang=lang, lead=lead,
    )


def _user_asks_pay_after_interview(user_text: str, history: list[dict] | None = None) -> bool:
    """Pay-after question in the CURRENT message — not stale thread context."""
    t = (user_text or "").lower()
    if _user_availability_ping(user_text, history) or _user_wants_demo(user_text):
        return False
    if any(m in t for m in _PAY_AFTER_INTERVIEW_MARKERS):
        return True
    if "after interview" in t and any(w in t for w in ("pay", "payment", "amount")):
        return True
    if any(w in t for w in ("cheyyocha", "cheyochaa", "avutunda", "possible")):
        if any(w in t for w in ("pay", "payment", "amount", "after interview")):
            return True
    return False


def _pay_after_interview_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    known = _known_facts_for_reply(history, qualification, user_text)
    tech = (known.get("tech_stack") or "").strip()
    round_t = (known.get("round_type") or "").strip()
    timing = (known.get("interview_timing") or "").strip()
    addr = _addr_prefix(lead, lang)
    contact = _call_senior_contact(history, user_text, qualification, lang=lang)

    detail = ""
    if tech and timing:
        detail = f"{tech} {round_t + ' ' if round_t else ''}round {timing} — "
    elif tech:
        detail = f"{tech} interview — "

    if lang == "english":
        return (
            f"Got it {addr}👍 {detail}payment is before the round — {_tech_team_demo_phrase(lang)}. "
            f"For exceptions connect senior: {contact}"
        )
    return (
        f"Got it {addr}👍 {detail}payment mundu settle avvali — {_tech_team_demo_phrase(lang)}. "
        f"Exceptions ki senior team: {contact}"
    )


def _enforce_no_repeat_qualify(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Don't re-ask tech/time/round when the thread already captured them."""
    known = _known_facts_for_reply(history, qualification, user_text)
    tech = (known.get("tech_stack") or "").strip()
    round_t = (known.get("round_type") or "").strip()
    timing = (known.get("interview_timing") or "").strip()
    timing_known = _has_interview_timing_known(known, history, user_text)
    lower = (reply_text or "").lower()

    if not any(
        m in lower
        for m in _REASK_KNOWN_QUALIFY_MARKERS + _ASK_TECH_MARKERS + _ASK_ROUND_MARKERS
    ):
        return reply_text

    if round_t and any(m in lower for m in _ASK_ROUND_MARKERS):
        known = _known_facts_for_reply(history, qualification, user_text)
        if _interview_fully_qualified(known, history, user_text):
            return _interview_support_smart_reply(
                known,
                history=history,
                user_text=user_text,
                qualification=qualification,
                lang=lang,
                lead=lead,
            )
        contextual = _reply_from_known_facts(
            known, lang=lang, history=history, user_text=user_text,
        )
        if contextual:
            return contextual

    if not (tech and timing_known):
        return reply_text

    if _user_asks_pay_after_interview(user_text, history):
        return _pay_after_interview_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        )

    addr = _addr_prefix(lead, lang)
    round_bit = f"{round_t} " if round_t else ""
    known = _known_facts_for_reply(history, qualification, user_text)
    if _interview_fully_qualified(known, history, user_text):
        return _interview_support_smart_reply(
            known,
            history=history,
            user_text=user_text,
            qualification=qualification,
            lang=lang,
            lead=lead,
        )
    if lang == "english":
        return (
            f"Got it {addr}👍 {tech} {round_bit}{timing} noted — {_tech_team_demo_phrase_short(lang)} 👍"
        )
    return (
        f"Got it {addr}👍 {tech} {round_bit}{timing} noted — {_tech_team_demo_phrase_short(lang)} 👍"
    )


def _reply_contradicts_known_facts(reply_text: str, known: dict) -> bool:
    lower = (reply_text or "").lower()
    round_t = (known.get("round_type") or "").strip().lower()
    timing = (known.get("interview_timing") or "").strip().lower()
    if round_t == "technical" and ("client round" in lower or " client " in lower):
        return True
    if round_t == "client" and ("technical round" in lower or " technical " in lower):
        return True
    if timing and "4:15" in timing and re.search(r"\b15\s*pm\b", lower) and "4:15" not in lower:
        return True
    return False


def _enforce_reply_matches_facts(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
) -> str:
    """Rewrite confirmations that contradict mined tech/round/timing."""
    known = _known_facts_for_reply(history, qualification, user_text)
    if not _reply_contradicts_known_facts(reply_text, known):
        return reply_text
    contextual = _reply_from_known_facts(
        known, lang=lang, history=history, user_text=user_text,
    )
    return contextual or reply_text


def _user_wants_proxy_call(user_text: str, history: list[dict] | None = None) -> bool:
    blob = _user_only_blob(history or [], user_text, tail=12)
    if any(m in blob for m in _PROXY_CALL_MARKERS):
        return True
    t = (user_text or "").lower()
    if "proxy" in t and any(
        x in blob for x in ("power bi", "powerbi", "interview", "round", "technical", "client round")
    ):
        return True
    return False


def _data_analyst_proxy_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Power BI / data leads asking proxy — qualify round; Vani closes pricing."""
    prefix = _reply_ack_prefix(lead, lang, history=history)
    if lang == "english":
        return (
            f"{prefix}Yes 👍 Power BI interview proxy support. "
            f"Client or technical round — and when is the interview? "
            f"Pricing & process → Vani 📞 {VANI_PHONE} 📲 {VANI_WHATSAPP}"
        )
    return (
        f"{prefix}Yes 👍 Power BI interview proxy support. "
        f"Client aa technical aa — interview epudu? "
        f"Price/process → Vani 📞 {VANI_PHONE} 📲 {VANI_WHATSAPP}"
    )


def _reply_denies_proxy(reply_text: str) -> bool:
    lower = (reply_text or "").lower()
    return any(m in lower for m in _PROXY_DENIAL_MARKERS)


def _proxy_high_volume(blob: str) -> bool:
    return any(w in blob for w in (
        "40", "50", "40-50", "40 to 50", "many calls", "too many",
        "multiple interviews", "bulk", "high volume",
    )) or (
        "per week" in blob
        and any(w in blob for w in ("40", "50", "many", "multiple", "bulk", "high"))
    )


def _proxy_call_service_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Proxy / shadow caller — expert attends interview on client's behalf. Never deny."""
    if _is_data_analyst_domain(history, user_text, qualification):
        return _data_analyst_proxy_reply(
            user_text,
            history=history,
            qualification=qualification,
            lang=lang,
            lead=lead,
        )

    user_blob = _user_only_blob(history or [], user_text, tail=12)
    en = lang == "english"
    prefix = _reply_ack_prefix(lead, lang, history=history)
    contact = _call_senior_contact(history, user_text, qualification, lang=lang)

    if _user_wants_phone_call(user_text, history):
        return _call_handoff_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        )

    if _proxy_high_volume(user_blob):
        if en:
            return f"{prefix}yes proxy/shadow caller. High volume — senior custom plan: {contact}"
        return f"{prefix}proxy/shadow caller untundi. High volume ki senior: {contact}"

    if _should_quote_price(user_text, history):
        if en:
            return (
                f"{prefix}yes proxy/shadow caller — expert attends per round. "
                f"Which tech stack?"
            )
        return f"{prefix}proxy/shadow caller untundi. Tech stack cheppandi?"

    if en:
        return (
            f"{prefix}yes proxy/shadow caller — expert attends on your behalf. "
            f"Which tech stack?"
        )
    return f"{prefix}proxy/shadow caller untundi. Tech stack cheppandi?"


def _enforce_proxy_service(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Never deny proxy/shadow caller — we offer this service."""
    if _user_wants_proxy_call(user_text, history) or _reply_denies_proxy(reply_text):
        if _is_data_analyst_domain(history, user_text, qualification):
            return _data_analyst_proxy_reply(
                user_text,
                history=history,
                qualification=qualification,
                lang=lang,
                lead=lead,
            )
        return _proxy_call_service_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        )
    lower = (reply_text or "").lower()
    if _is_data_analyst_domain(history, user_text, qualification) and (
        "how many calls" in lower or "per week" in lower or "weekly" in lower
    ):
        return _data_analyst_proxy_reply(
            user_text,
            history=history,
            qualification=qualification,
            lang=lang,
            lead=lead,
        )
    return reply_text


def _count_payment_qrs_sent(slot: str, user_id: int) -> int:
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    n = 0
    for m in conv.get("messages") or []:
        if m.get("direction") != "out":
            continue
        text = (m.get("text") or "").lower()
        if "payment qr" in text or text.strip() in {"💵 payment qr", "📷 payment qr"}:
            n += 1
    return n


def _payment_qr_allowed(
    *,
    user_text: str,
    history: list[dict],
    stage: str,
    next_stage: str,
    ai_out: dict,
    slot: str,
    user_id: int,
    state: dict,
) -> bool:
    """Block premature or repeated QR — trust first, payment only when lead is ready."""
    if not ai_out.get("send_payment_qr"):
        return False
    if _user_deferred(user_text) or _user_probes_identity(user_text) or _user_asks_name(user_text):
        return False
    if _is_price_inquiry(user_text):
        return False
    qr_sent = int(state.get("payment_qr_sent_count") or 0) or _count_payment_qrs_sent(slot, user_id)
    t = (user_text or "").lower()
    user_wants_qr_again = "qr" in t or "send payment" in t
    if qr_sent >= 1 and not user_wants_qr_again:
        return False
    if not _user_ready_for_payment(user_text):
        return False
    return True


def _conversation_blob(history: list[dict], user_text: str, *, tail: int = 10) -> str:
    parts = [(m.get("content") or "") for m in (history or [])[-tail:]]
    parts.append(user_text or "")
    return " ".join(parts).lower()


def _tech_needle_in_blob(needle: str, blob: str) -> bool:
    """Avoid false tech hits from short substrings (e.g. mean inside random words)."""
    n = (needle or "").lower().strip()
    b = (blob or "").lower()
    if not n or not b:
        return False
    if n in {"go", "vue", "sap", "php", "aws"}:
        return bool(re.search(rf"\b{re.escape(n)}\b", b))
    return n in b


def _user_requests_ai_off(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in _USER_AI_OPT_OUT_MARKERS)


def _user_reports_service_failure(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in _SERVICE_COMPLAINT_MARKERS)


def _lead_has_human_owned_thread(slot: str, user_id: int) -> bool:
    """Human operators engaged — AI must not take over (paid thread OR live handoff)."""
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    msgs = conv.get("messages") or []
    human_out = 0
    blob_parts: list[str] = []
    for m in msgs:
        text = (m.get("text") or "").strip()
        if text:
            blob_parts.append(text.lower())
        if m.get("direction") == "out" and not m.get("ai"):
            human_out += 1
    if human_out < 2:
        return False
    blob = " ".join(blob_parts)
    if any(m in blob for m in _USER_REJECTED_AI_MARKERS):
        return True
    if human_out >= 3:
        return True
    if human_out >= 2 and any(m in blob for m in _HUMAN_OPERATOR_MARKERS):
        return True
    return any(m in blob for m in _HUMAN_OWNED_THREAD_MARKERS)


def _client_turn_waiting(slot: str, user_id: int) -> bool:
    """True when the client's message is last — nobody has replied to this turn yet."""
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    msgs = conv.get("messages") or []
    if not msgs:
        return False
    return msgs[-1].get("direction") == "in"


def _karthik_resume_waiting_client(slot: str, user_id: int, state: dict) -> dict:
    """Human-owned threads stay manual only while a human is actively on the turn.

    If the client messaged again and is still unanswered, Karthik may resume.
    """
    reason = (state.get("_disable_reason") or "").strip()
    if reason != "human_owned":
        return state
    if not _client_turn_waiting(slot, user_id):
        return state
    return enable_for_lead(slot, int(user_id))


def _human_only_lock_reason(slot: str, user_id: int, user_text: str) -> str | None:
    if _user_requests_ai_off(user_text):
        return "user_opt_out"
    if _lead_has_human_owned_thread(slot, user_id):
        if _client_turn_waiting(slot, user_id):
            return None
        if _user_reports_service_failure(user_text):
            return "service_complaint"
        return "human_owned"
    return None


def _is_operator_defer_active(slot: str, user_id: int) -> bool:
    """Human operator said 'give me time' — Karthik stays out until they reply again."""
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    msgs = list(conv.get("messages") or [])
    defer_idx: int | None = None
    for i, m in enumerate(msgs):
        if m.get("direction") != "out" or m.get("ai"):
            continue
        text = (m.get("text") or "").lower()
        if any(p in text for p in _OPERATOR_DEFER_MARKERS):
            defer_idx = i
    if defer_idx is None:
        return False
    for m in msgs[defer_idx + 1:]:
        if m.get("direction") == "out" and not m.get("ai"):
            text = (m.get("text") or "").lower()
            if not any(p in text for p in _OPERATOR_DEFER_MARKERS):
                return False
    return True


def _user_wants_job_help(user_text: str, history: list[dict] | None) -> bool:
    blob = _conversation_blob(history or [], user_text)
    if any(m in blob for m in _JOB_SEEKER_MARKERS):
        return True
    if any(m in blob for m in _LAYOFF_MARKERS) and any(
        w in blob for w in ("job", "help", "support", "placement", "hire")
    ):
        return True
    return False


def _user_asks_backdoor_jobs(user_text: str, history: list[dict] | None) -> bool:
    blob = _conversation_blob(history or [], user_text or "", tail=24)
    return any(m in blob for m in _BACKDOOR_JOB_MARKERS) or (
        "backdoor" in blob and "job" in blob
    )


def _backdoor_jobs_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """No backdoor placements — only legitimate interview support when they have a round."""
    addr = _addr_prefix(lead, lang)
    en = lang == "english"
    blob = _conversation_blob(history or [], user_text or "", tail=20)
    layoff = any(m in blob for m in _LAYOFF_MARKERS)
    if en:
        sorry = f"Sorry about the layoff {addr}👍 " if layoff else ""
        return (
            f"{sorry}We do not arrange backdoor jobs or guaranteed placements without interviews. "
            f"We only help with genuine interview prep and live interview support when you already "
            f"have a scheduled client/technical round. If you have an interview coming up, share your "
            f"tech stack and round date 👍"
        )
    sorry = f"Layoff ki sorry {addr}👍 " if layoff else ""
    return (
        f"{sorry}Backdoor jobs / fake placements cheyam — interview schedule unnapudu "
        f"genuine prep & live support matrame. Tech stack + round date share cheyyandi 👍"
    )


_JOB_SUPPORT_DECLINED_MARKERS = (
    "not providing job support",
    "we not providing job support",
    "we're not providing job support",
    "don't provide job support",
    "do not provide job support",
    "no job support",
)
_INDIA_JOB_SUPPORT_REQUEST_MARKERS = (
    "job support",
    ".net job support",
    "dotnet job support",
    "java job support",
    "python job support",
    "need job support",
    "provide job support",
    "do you provide job support",
    "placement support",
    "job placement support",
)


def _user_requests_india_job_support(
    user_text: str,
    history: list[dict] | None = None,
) -> bool:
    """On-the-job / placement-style job support in India — not offered."""
    if _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history):
        return False
    if _user_offers_support_to_candidates(user_text, history) or _user_offers_support_to_candidates(
        "", history,
    ):
        return False
    if _user_thread_targets_abroad(history, user_text):
        return False
    blob = _user_only_blob(history or [], user_text, tail=12)
    if any(m in blob for m in _INDIA_JOB_SUPPORT_REQUEST_MARKERS):
        if "interview support" in blob and "job support" not in blob:
            return False
        return True
    t = (user_text or "").lower()
    return "job support" in t and not _user_thread_targets_abroad(history, user_text)


def _team_declined_job_support_in_history(history: list[dict] | None) -> bool:
    for m in history or []:
        if (m.get("role") or "").lower() not in ("assistant",):
            continue
        c = (m.get("content") or "").lower()
        if any(mk in c for mk in _JOB_SUPPORT_DECLINED_MARKERS):
            return True
    return False


def _job_support_thread_closed(user_text: str, history: list[dict] | None) -> bool:
    """Human already said no job support — Karthik must not re-pitch services."""
    if _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history):
        return False
    if not _team_declined_job_support_in_history(history):
        return False
    if _user_requests_india_job_support(user_text, history):
        return True
    t = (user_text or "").strip().lower()
    if t in ("okay", "ok", "k", "thanks", "thank you", "thankyou"):
        return True
    if any(w in t for w in ("know any", "know anyone", "anyone", "any one", "refer")):
        return True
    if _user_wants_interview_support(user_text, history) and "job support" not in t:
        return False
    return True


def _reply_looks_like_india_job_support_denial(reply_text: str) -> bool:
    lower = (reply_text or "").lower()
    return any(
        x in lower
        for x in (
            "no job support",
            "job support ledu",
            "not providing job support",
            "interview support only",
        )
    )


def _india_no_job_support_reply(
    *,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    addr = _addr_prefix(lead, lang)
    if lang == "english":
        return (
            f"Sorry {addr}👍 no job support in India. "
            f"Interview support only if you have a scheduled round 👍"
        )
    return (
        f"Sorry {addr}👍 India lo job support ledu. "
        f"Scheduled interview unte interview support matrame 👍"
    )


def _job_support_closed_ack(lang: str, lead: dict | None) -> str:
    addr = _addr_prefix(lead, lang)
    if lang == "english":
        return f"Got it {addr}👍 all the best 👍"
    return f"Got it {addr}👍 parledu — all the best 👍"


def _enforce_india_job_support_policy(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    if _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history):
        if _reply_looks_like_india_job_support_denial(reply_text):
            return _support_provider_inbound_reply(
                user_text, history=history, lang=lang, lead=lead,
            )
        return reply_text
    if _user_thread_targets_abroad(history, user_text) and not _user_requests_india_job_support(
        user_text, history,
    ):
        return reply_text
    if _job_support_thread_closed(user_text, history):
        lower = (reply_text or "").lower()
        if any(
            x in lower
            for x in (
                "interview", "resume", "naukri", "help you", "let me know",
                "what can i help", "job search",
            )
        ):
            return _job_support_closed_ack(lang, lead)
        return reply_text
    if _user_requests_india_job_support(user_text, history):
        return _india_no_job_support_reply(lang=lang, lead=lead)
    return reply_text


_ABROAD_REGION_MARKERS = (
    "outside india", "outside of india", "jobs outside india", "job outside india",
    "abroad", "overseas", "international job", "international market",
    "europe", " uk", "uk ", "united kingdom", "germany", "france", "netherlands",
    "canada", "usa", "us jobs", "u.s.", "australia", "melbourne", "dubai", "uae",
    "singapore", "foreign country", "other country", "another country",
)

_ABROAD_JOB_PLACEMENT_MARKERS = (
    "find jobs", "find job", "help to find jobs", "help find jobs", "job search",
    "looking for a job", "looking for job", "need a job", "job applications",
    "get interview calls", "getting interview calls", "not getting interview calls",
    "not getting calls", "interview calls", "arrange interview", "job placement",
    "assist with job", "job applications in", "jobs in europe", "jobs in uk",
)

_ABROAD_FALSE_PROMISE_MARKERS = (
    "job applications in europe", "job applications in the uk", "job applications abroad",
    "assist with job searches abroad", "job searches abroad", "help with job applications",
    "we can help with job applications", "applications in europe and the uk",
    "will help you to get interview calls", "get help interview calls",
    "help you get interview calls", "provide interview calls in india itself",
)


def _abroad_region_label(history: list[dict] | None, user_text: str = "") -> str:
    blob = _conversation_blob(history or [], user_text, tail=30).lower()
    if "europe" in blob and "uk" in blob:
        return "Europe / UK"
    if "europe" in blob:
        return "Europe"
    if " uk" in blob or blob.strip() == "uk" or "united kingdom" in blob:
        return "UK"
    if "usa" in blob or " us " in blob or "united states" in blob:
        return "US"
    if "canada" in blob:
        return "Canada"
    if "australia" in blob or "melbourne" in blob:
        return "Australia"
    return "abroad"


def _user_thread_targets_abroad(
    history: list[dict] | None,
    user_text: str = "",
) -> bool:
    blob = _conversation_blob(history or [], user_text, tail=30).lower()
    user_blob = _user_only_blob(history or [], user_text, tail=16).lower()
    if any(m in blob for m in _ABROAD_REGION_MARKERS):
        return True
    return any(
        m in user_blob
        for m in ("outside india", "outside of india", "jobs outside", "job outside")
    )


def _user_wants_abroad_job_placement(
    user_text: str,
    history: list[dict] | None,
) -> bool:
    """Job finding / interview-call sourcing outside India — we do not offer this."""
    if not _user_thread_targets_abroad(history, user_text):
        return False
    if _user_wants_interview_support(user_text, history):
        return False
    blob = _user_only_blob(history or [], user_text, tail=20).lower()
    if any(m in blob for m in _ABROAD_JOB_PLACEMENT_MARKERS):
        return True
    if _user_wants_job_help(user_text, history):
        return True
    if _user_wants_job_search_support(user_text, history):
        return True
    full = _conversation_blob(history or [], user_text, tail=20).lower()
    if "outside india" in full or "outside of india" in full:
        if any(w in full for w in ("job", "jobs", "find", "call", "placement", "naukri")):
            return True
    return False


def _abroad_job_policy_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Abroad: resume + interview prep/support only — no job placement or call sourcing."""
    addr = _addr_prefix(lead, lang)
    region = _abroad_region_label(history, user_text)
    en = lang == "english"
    if en:
        return (
            f"Got it {addr}👍 for {region}: we do NOT find jobs or arrange interview calls "
            f"outside India (that job/call placement is India only). We CAN help with resume building, "
            f"interview prep, and live interview support when you already have a scheduled round abroad. "
            f"What do you need — resume or interview prep?"
        )
    return (
        f"Got it {addr}👍 {region} ki jobs dorakatam / interview calls arrange cheyadam India lo matrame — "
        f"abroad ki resume, interview prep, scheduled round unte live support help chestham. "
        f"Resume na interview prep na?"
    )


def _enforce_abroad_job_policy(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    if not _user_thread_targets_abroad(history, user_text):
        return reply_text
    lower = (reply_text or "").lower()
    if any(m in lower for m in _ABROAD_FALSE_PROMISE_MARKERS):
        return _abroad_job_policy_reply(user_text, history=history, lang=lang, lead=lead)
    if _reply_looks_like_naukri_pitch(reply_text) or "automation call package" in lower:
        return _abroad_job_policy_reply(user_text, history=history, lang=lang, lead=lead)
    if "naukri" in lower and any(w in lower for w in ("call", "calls", "recruiters find")):
        return _abroad_job_policy_reply(user_text, history=history, lang=lang, lead=lead)
    if any(
        m in lower
        for m in (
            "job applications in",
            "help with job applications",
            "assist with job search",
            "interview calls in india",
        )
    ):
        return _abroad_job_policy_reply(user_text, history=history, lang=lang, lead=lead)
    return reply_text


def _user_reopened_after_bye(user_text: str, history: list[dict] | None) -> bool:
    t = (user_text or "").lower().strip().rstrip("!.,")
    if t not in {"hlo", "hello", "hi", "hey", "hii", "helo", "hlw", "hiiii"}:
        return False
    blob = _conversation_blob(history or [], "", tail=10)
    return any(m in blob for m in _BYE_MARKERS)


def _job_seeker_reply(
    user_text: str,
    *,
    history: list[dict] | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    if _user_offers_support_to_candidates(user_text, history) or _user_offers_support_to_candidates("", history):
        return _support_provider_inbound_reply(
            user_text, history=history, qualification=None, lang=lang, lead=lead,
        )
    if _user_asks_backdoor_jobs(user_text, history) or _user_asks_backdoor_jobs("", history):
        return _backdoor_jobs_reply(user_text, history=history, lang=lang, lead=lead)
    if _user_wants_abroad_job_placement(user_text, history) or _user_wants_abroad_job_placement("", history):
        return _abroad_job_policy_reply(user_text, history=history, lang=lang, lead=lead)
    addr = _addr_prefix(lead, lang)
    en = lang == "english"
    if en:
        return (
            f"Got it {addr}👍 we help with interview support when you have a scheduled round. "
            f"What's your tech stack?"
        )
    return (
        f"Got it {addr}👍 scheduled interview unte interview support help chestham. "
        f"Tech stack cheppandi?"
    )


def _reopen_after_bye_reply(lang: str = "english", lead: dict | None = None) -> str:
    addr = _addr_prefix(lead, lang)
    if lang == "english":
        return f"Hi {addr}👍 I'm here — interview support, resume, or Naukri?"
    return f"Hi {addr}👍 cheppandi — interview support, resume, leda Naukri?"


def _user_seeks_dev_collaboration(user_text: str, history: list[dict] | None) -> bool:
    """Inbound hiring us as a developer / project collaborator — NOT a job seeker."""
    intent = resolve_thread_intent(history, user_text)
    if intent_blocks_dev_collab(intent):
        return False
    if has_interview_context(_intent_user_blob(history, user_text)):
        return False
    blob = _user_only_blob(history or [], user_text or "", tail=24)
    if any(m in blob for m in _DEV_COLLAB_MARKERS):
        return True
    if any(m in blob for m in _DEV_HIRE_QUESTION_MARKERS):
        return True
    if "github" in blob and any(m in blob for m in _GITHUB_INVITE_MARKERS):
        return True
    return False


def _reply_claims_dev_services(reply_text: str) -> bool:
    lower = (reply_text or "").lower()
    return any(m in lower for m in _DEV_SERVICE_CLAIM_MARKERS)


def _dev_collaboration_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Politely decline dev freelancing — never pretend to be a project developer."""
    addr = _addr_prefix(lead, lang)
    en = lang == "english"
    t = (user_text or "").lower()
    blob = _conversation_blob(history or [], user_text or "", tail=12)
    asks_github = any(m in t for m in _GITHUB_INVITE_MARKERS) or any(
        m in blob for m in _GITHUB_INVITE_MARKERS
    )
    if asks_github:
        if en:
            return (
                f"Sorry {addr}we don't take freelance dev work or share GitHub for repo access 👍 "
                f"we help IT candidates with interview prep & job support. "
                f"Best of luck finding the right dev for your project!"
            )
        return (
            f"Sorry {addr}freelance dev work / GitHub repo access cheyamu 👍 "
            f"IT candidates ki interview prep & job support help chestham. "
            f"Mee project ki right developer dorukutaru — all the best!"
        )
    if en:
        return (
            f"Got it {addr}👍 we're not available for dev collaboration on projects — "
            f"we focus on interview prep & job support for job seekers. "
            f"Hope you find a great developer for your build!"
        )
    return (
        f"Got it {addr}👍 project dev collaboration cheyamu — "
        f"job seekers ki interview prep & job support help chestham. "
        f"Mee project ki manchi developer dorukutaru 👍"
    )


# ── Conversation memory (mine facts from full thread) ───────────────────────

_TECH_DETECT = (
    ("node.js", "Node.js"), ("nodejs", "Node.js"), ("node js", "Node.js"),
    ("react.js", "React"), ("react", "React"), ("angular", "Angular"),
    ("vue", "Vue"), ("java", "Java"), ("python", "Python"), ("django", "Django"),
    (".net", ".NET"), ("dotnet", ".NET"), ("c#", "C#"), ("golang", "Go"),
    ("go lang", "Go"), ("php", "PHP"), ("laravel", "Laravel"), ("spring", "Spring"),
    ("aws", "AWS"), ("devops", "DevOps"), ("full stack", "Full Stack"),
    ("mern", "MERN"), ("mean stack", "MEAN"), ("flutter", "Flutter"), ("kotlin", "Kotlin"),
    ("swift", "Swift"),
    ("marketing cloud", "Salesforce Marketing Cloud"),
    ("salesforce", "Salesforce"),
    ("sap", "SAP"),
    ("servicenow", "ServiceNow"), ("service now", "ServiceNow"),
)

# Staff contact details are loaded from the git-ignored staff directory
# (config/staff_directory.json). Source keeps only role slugs — no real
# names/numbers. See core/staff_directory.py and docs/STAFF_DIRECTORY.md.
from core import staff_directory as _staff

THRILOK_PHONE = _staff.phone("senior_tech")
THRILOK_WHATSAPP = _staff.whatsapp("senior_tech")
# Senior data / Power BI / analytics handoff (data_lead — not the persona)
VANI_PHONE = _staff.phone("data_lead")
VANI_WHATSAPP = _staff.whatsapp("data_lead")
SATYA_PHONE = VANI_PHONE
SATYA_WHATSAPP = VANI_WHATSAPP
NIKHILA_PHONE = _staff.phone("react_lead_a")
NIKHILA_WHATSAPP = _staff.whatsapp("react_lead_a")
BHAVANA_PHONE = _staff.phone("react_lead_b")
BHAVANA_WHATSAPP = _staff.whatsapp("react_lead_b")
KALYAN_PHONE = _staff.phone("devops_lead")
KALYAN_WHATSAPP = _staff.whatsapp("devops_lead")


def _allowed_outbound_phone_tails() -> set[str]:
    tails: set[str] = set()
    for raw in (
        THRILOK_PHONE,
        VANI_PHONE,
        NIKHILA_PHONE,
        BHAVANA_PHONE,
        KALYAN_PHONE,
    ):
        digits = re.sub(r"\D", "", raw or "")
        if len(digits) >= 10:
            tails.add(digits[-10:])
    return tails


_PHONE_IN_TEXT_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")


def _phone_tail(phone_constant: str) -> str:
    return re.sub(r"\D", "", phone_constant or "")[-10:]


def _enforce_senior_contact_routing(
    reply_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
) -> str:
    """Use only the senior that matches stack/domain (e.g. not Kalyan for Salesforce)."""
    s = (reply_text or "").strip()
    if not s or not _PHONE_IN_TEXT_RE.search(s):
        return s
    kalyan = _phone_tail(KALYAN_PHONE)
    vani = _phone_tail(VANI_PHONE)
    wrong = False
    for m in _PHONE_IN_TEXT_RE.finditer(s):
        tail = re.sub(r"\D", "", m.group(0))[-10:]
        if tail == kalyan and not _is_devops_domain(history, "", qualification):
            wrong = True
            break
        if tail == vani and not _is_data_analyst_domain(history, "", qualification):
            wrong = True
            break
    if wrong:
        return _senior_handoff_reply(
            empathy=False,
            history=history,
            user_text="",
            qualification=qualification,
        )
    return s


def _enforce_whitelisted_contacts(
    reply_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
) -> str:
    """Drop or replace phone numbers Karthik must not invent (e.g. random WhatsApp)."""
    s = _enforce_senior_contact_routing(
        reply_text, history=history, qualification=qualification, lang=lang,
    )
    if not s:
        return s
    allowed = _allowed_outbound_phone_tails()
    bad: list[str] = []
    for m in _PHONE_IN_TEXT_RE.finditer(s):
        tail = re.sub(r"\D", "", m.group(0))[-10:]
        if tail and tail not in allowed:
            bad.append(tail)
    if not bad:
        return s
    lines = [ln.strip() for ln in re.split(r"\n+", s) if ln.strip()]
    kept: list[str] = []
    for ln in lines:
        ln_tail = ""
        pm = _PHONE_IN_TEXT_RE.search(ln)
        if pm:
            ln_tail = re.sub(r"\D", "", pm.group(0))[-10:]
        if ln_tail and ln_tail in bad:
            continue
        kept.append(ln)
    if kept:
        out = "\n\n".join(kept)
        if not _PHONE_IN_TEXT_RE.search(out) or all(
            re.sub(r"\D", "", m.group(0))[-10:] in allowed for m in _PHONE_IN_TEXT_RE.finditer(out)
        ):
            return out
    return _senior_handoff_reply(
        empathy=False,
        history=history,
        user_text="",
        qualification=qualification,
    )

_DATA_ANALYST_MARKERS = (
    "data analyst", "junior data analyst", "senior data analyst", "business analyst",
    "bi analyst", "business intelligence", "power bi", "powerbi", "tableau",
    "reporting analyst", "mis analyst", "mis executive", "sql developer",
    "data visualization", "dashboard developer", "excel analyst", "product analyst",
    "operations analyst", "financial analyst", "marketing analyst", "hr analyst",
    "research analyst", "insights analyst", "kpi analyst", "data quality analyst",
    "database analyst", "analytics consultant", "etl developer", "data operations",
    "crm analyst", "workforce analyst", "forecasting analyst", "statistical analyst",
    "healthcare data analyst", "supply chain analyst", "revenue analyst",
    "analytics engineer", "python data analyst", "ai/data analyst", "data analytics",
    "data analysis", "bi developer", "tableau developer", "power bi developer",
    "business intelligence developer",
)

_REACT_FRONTEND_MARKERS = (
    "react js developer", "react.js developer", "react developer", "react frontend",
    "angular developer", "angular technology", "angular js", "angularjs",
    "frontend developer", "frontend engineer", "ui developer", "ui engineer",
    "javascript developer", "react native", "mern stack", "mern developer",
    "next.js developer", "nextjs developer", "typescript frontend",
    "spa developer", "single page application", "pwa developer", "progressive web app",
    "web application developer", "client-side developer", "client side developer",
    "responsive web developer", "cross-platform app developer", "react ui engineer",
    "software engineer frontend", "software engineer – frontend", "software engineer - frontend",
    "react support developer", "react production support", "react + api", "react + redux",
    "react + firebase", "react full stack", "react fullstack", "web developer",
    "react frontend developer", "react js", "reactjs",
)

_JAVA_MARKERS = (
    "java developer", "core java", "java backend", "backend engineer (java)",
    "java software engineer", "java application developer", "java web developer",
    "full stack java", "java full stack", "spring boot", "spring framework",
    "java microservices", "rest api developer (java)", "j2ee", "java ee",
    "hibernate developer", "jdbc developer", "java api developer",
    "enterprise java", "java cloud developer", "java aws developer",
    "java integration developer", "kafka java", "java production support",
    "java support developer", "java application support", "selenium with java",
    "java test automation", "react + java", "java + react", "angular + java",
    "java + angular", "senior java developer", "lead java developer",
    "java technical lead", "java architect",
)

_AI_ML_MARKERS = (
    "ai engineer", "artificial intelligence engineer", "machine learning engineer",
    "ai/ml engineer", "generative ai", "genai developer", "llm engineer",
    "prompt engineer", "ai developer", "ai software engineer", "ai application developer",
    "ai research engineer", "machine learning developer", "deep learning engineer",
    "nlp engineer", "natural language processing engineer", "computer vision engineer",
    "data scientist", "applied ai engineer", "ai automation engineer", "ai chatbot developer",
    "conversational ai engineer", "rag engineer", "langchain developer", "ai agent developer",
    "ai integration engineer", "mlops engineer", "ai infrastructure engineer",
    "ai platform engineer", "ai cloud engineer", "ai backend developer",
    "recommendation systems engineer", "intelligent automation engineer",
    "robotics ai engineer", "ai solutions architect", "ai consultant", "ai product engineer",
    "openai integration", "autonomous systems engineer", "ai support engineer",
    "ai qa engineer", "ai test engineer",
)

_DEVOPS_MARKERS = (
    "devops engineer", "devops architect", "senior devops", "lead devops",
    "cloud devops", "aws devops", "azure devops", "gcp devops",
    "site reliability engineer", " sre ", "platform engineer", "infrastructure engineer",
    "cloud engineer", "cloud infrastructure", "cloud operations engineer",
    "kubernetes engineer", "kubernetes", "docker engineer", " docker ", "openshift engineer",
    "openshift", "ci/cd engineer", "ci/cd pipeline", "ci cd", "build engineer",
    "release engineer", "build & release", "build and release",
    "infrastructure automation engineer", "automation engineer",
    "terraform engineer", " terraform ", "ansible engineer", " ansible ",
    "jenkins engineer", " gitops ", "linux system engineer", "linux administrator",
    "system administrator", "deployment engineer", "monitoring engineer",
    "observability engineer", "production support engineer", "application support engineer",
    "reliability engineer", "platform reliability", "devsecops", "security devops",
    "devops consultant", "devops support",
)

_PREMATURE_SLOT_MARKERS = (
    "block the slot", "blocked the slot", "slot confirmed", "slot is confirmed",
    "let's block", "lets block", "we can block", "book the slot", "slot book",
    "confirm the slot", "slot is booked", "booking confirmed", "block your slot",
    "let's block the slot", "lets block the slot",
)

_DOUBT_MARKERS = (
    "too expensive", " costly", "not sure", "let me think", "need to think",
    "not convinced", "don't trust", "dont trust", "scam", "fraud", "doubt",
    "why should i pay", "no money", "can't pay", "cant pay", "not interested in paying",
)

_PAY_AFTER_INTERVIEW_MARKERS = (
    "pay after interview", "pay after the interview", "payment after interview",
    "payment after the interview", "pay after my interview", "after interview pay",
    "after the interview pay", "will pay after interview", "pay later after interview",
    "interview tarvata pay", "interview tarvata payment", "interview ayyaka pay",
    "interview ayyaka payment", "interview ki tarvata", "interview ki tarvata pay",
    "interview tarvata cheyy", "after interview cheyy", "after interview avutunda",
)

_REASK_KNOWN_QUALIFY_MARKERS = (
    "tech & interview", "tech and interview", "interview epudu", "interview date & time",
    "when is your interview date", "when is your interview", "which tech stack", "what tech stack",
    "client round or technical", "client round aa technical",
    "when is the interview", "interview date & time",
)

_URGENCY_EMPATHY_MARKERS = (
    "dependents", "financial", "important interview", "please help", "need to clear",
    "urgent", "unnava", "pressure", "convince", "convinced",
)

_REPEAT_COMPLAINT_MARKERS = (
    "already", "same question", "again your", "again you're", "again ur",
    "you know right", "u know right", "you know", "u know", "told you",
    "said already", "said you", "how bad", "idiot", "stupid", "useless",
    "asked again", "asking again", "repeat", "forgot",
    "em adiga", "nenu em adiga", "yem chp", "yem chep", "nuvvu yem",
    "what did i ask", "wrong answer", "not answering",
)

_PROCESS_QUESTION_MARKERS = (
    "how you will assist", "how will you assist", "how do you assist", "how you assist",
    "how will you help", "how do you help", "assist during", "during the interview",
    "how does it work", "how it works", "explain how", "what exactly do you",
    "what will you do", "what do you do during", "how can you help during",
    "elaborate", "explain in detail", "tell me more about",
)

_FREE_CONFUSION_MARKERS = (
    "thought it was free", "free service", "without payment", "social platform",
    "confirmed the slot without", "thought this is free", "thank you for your free",
    "thought it is a free", "i thought this is",
)

_DODGE_REPLY_MARKERS = (
    "let me know if you want to proceed", "let me know if you need",
    "if you want to proceed", "let me know if you'd like",
)

_ASK_TECH_MARKERS = (
    "tech stack", "which tech", "what tech", "technology stack", "working with",
)
_ASK_NEED_MARKERS = (
    "what do you need", "what support", "what are you looking", "tell me what you need",
    "what can i assist", "how can i help",
)

_OFFER_LETTER_MARKERS = (
    "till offer letter", "until offer letter", "offer letter", "till offer", "until offer",
    "support till offer", "support until offer", "all rounds till", "all interview rounds",
    "full interview support", "support till the offer", "support until the offer",
)

_JOB_SUPPORT_MARKERS = (
    "job support", "after joining", "on the job", "in the job", "work support",
    "post joining", "on-job support", "at workplace", "after i join",
)

_AUTOMATION_CALL_MARKERS = (
    "not getting calls", "not getting call", "no calls", "not receiving calls",
    "calls are not coming", "calls aren't coming", "calls not coming",
    "automation call", "search appearance", "call automation",
)
_NAUKRI_PROFILE_MARKERS = (
    "naukri profile", "create naukri", "naukri setup", "naukri account",
    "optimize naukri", "naukri optimization",
)
_RESUME_BUILDING_MARKERS = (
    "resume building", "build resume", "update resume", "create resume",
    "need resume", "professional resume", "ats resume",
    "documents to keep", "documents for resume", "need documents",
    "document for resume", "resume documents", "keep resume",
    "experience documents", "experience letter", "experience certificate",
    "relieving letter", "employment documents", "company documents",
)
_DOCUMENT_RESUME_MARKERS = (
    "documents to keep", "documents for resume", "need documents",
    "document for resume", "resume documents", "keep resume",
    "experience documents", "experience letter", "experience certificate",
    "relieving letter", "employment documents", "company documents",
    "documentation for resume", "docs for resume", "experience doc",
)
_INTERVIEW_NOT_SCHEDULED_MARKERS = (
    "not yet started", "not started yet", "haven't started", "have not started",
    "no interview yet", "interview not yet", "not scheduled", "not yet scheduled",
    "don't have interview", "no date yet", "interview not started", "no interview date",
)
_JOB_SEEKER_MARKERS = (
    "help me to get job", "help me get job", "help me get a job", "help get job",
    "need a job", "need job", "want a job", "want job", "get me a job",
    "looking for job", "looking for a job", "job please", "please help me get",
)
_BACKDOOR_JOB_MARKERS = (
    "backdoor job", "backdoor jobs", "back door job", "back door jobs",
    "backdoor placement", "backdoor opening", "backdoor opportunity",
    "eipisthara", "isthara for real time",
)
_LAYOFF_MARKERS = (
    "layoff", "laid off", "lost job", "lost my job", "lost job in",
    "recently fired", "got fired", "company closed",
)
# Expert offers interview support FOR our candidates (not a job seeker).
_PROVIDER_OFFERS_SUPPORT_MARKERS = (
    "looking to provide support",
    "looking to provide",
    "i'm looking to provide",
    "i am looking to provide",
    "provide support in",
    "providing support in",
    "offering support in",
    "offer support in",
    "i provide support",
    "we provide support",
    "candidates who require",
    "candidates who need",
    "candidates who want",
    "candidates require my",
    "do you have candidates",
    "if you have candidates",
    "any candidates who",
    "who require my support",
    "who need my support",
    "require my supp",
    "need my supp",
    "job support opportunities in",
)
_PROVIDER_ON_JOB_TASK_MARKERS = (
    "only job support",
    "not interview support",
    "not interview",
    "no interview",
    "project task",
    "project tasks",
    "task support",
    "assignment support",
    "on the job",
    "on-job",
    "work support",
    "after joining",
    "post joining",
    "help with project",
    "help with tasks",
)
_DEV_COLLAB_MARKERS = (
    "looking for a dev", "looking for dev", "looking for developer",
    "looking for a developer", "need a dev", "need a developer",
    "hire a dev", "hire a developer", "dev to collaborate",
    "developer to collaborate", "collaborate with me",
    "work on my project", "work on our project",
    "share your github username", "share your github", "your github username",
    "invite you to the repository", "invite you to the repo",
    "access to the github", "access to github repo",
    "give you access to the git", "evaluate your development skills",
    "evaluate your dev skills", "github repo so you can",
    "repo so you can take a look", "ecommerce site for our",
    "e-commerce site for our", "for our e-shop", "our e-shop",
    "redesign them", "previous developer", "built by a previous developer",
    "development skills", "project is still in development",
    "exists only on github",
)
_DEV_HIRE_QUESTION_MARKERS = (
    "are you full stack", "are you a full stack", "are you developer",
    "are you a developer", "you full stack", "you available for",
    "full stack dev?", "fullstack dev?",
)
_GITHUB_INVITE_MARKERS = (
    "share your github", "your github username", "github username",
    "invite you to the repo", "invite you to the repository",
    "give you access",
)
_DEV_SERVICE_CLAIM_MARKERS = (
    "full stack developer", "i'm a full stack", "i am a full stack",
    "i can help with redesign", "share more details about your project",
    "which pages need improvement", "i'm a developer", "i am a developer",
    "available for your project", "collaborate on your", "i can help with redesigning",
)
_OPERATOR_DEFER_MARKERS = (
    "give me time", "give me some time", "i will let you know", "will let you know",
    "let you know", "give me few days", "need some time",
    "on another call", "another call", "will get back", "get back to you",
    "just wait", "team will respond", "team will repond", "informed my team",
)
_AI_DISABLE_STICKY_REASONS = frozenset({
    "user_opt_out",
    "human_owned",
    "manual",
    "service_complaint",
})
_USER_AI_OPT_OUT_MARKERS = (
    "turn off this bot",
    "turn off bot",
    "turn off the bot",
    "stop bot",
    "stop this bot",
    "stop the bot",
    "bot reply",
    "stop auto reply",
    "stop automated",
    "disable bot",
    "no bot",
    "shut off bot",
    "kill the bot",
    "please turn off",
)
_PAYMENT_THREAD_MARKERS = (
    "received 3k",
    "received 5k",
    "payment",
    "phonepe",
    "phone pay",
    "paytm",
    "upi",
    "transferred",
    "transferring",
    "paid",
    "confirm payment",
    "pay the amount",
    "remaining payment",
)
_HUMAN_OWNED_THREAD_MARKERS = _PAYMENT_THREAD_MARKERS + _JOB_SUPPORT_DECLINED_MARKERS + (
    "ultraviewer",
    "anydesk",
    "meet.google",
    "confirm slot",
    "remotely connect",
)
_HUMAN_OPERATOR_MARKERS = (
    "this is vani",
    "hi this is vani",
    "this is kalyan",
    "i can pass the test",
    "call me on this number",
    "call me on watsup",
    _staff.phone_digits("data_lead"),
    _staff.phone_digits("devops_lead"),
    _staff.phone_digits("operator_extra"),
    "ping me your number",
    "fyn i can support",
)
_USER_REJECTED_AI_MARKERS = (
    "don't need your help",
    "don't need your help.",
    "you don't understand",
    "are you a robot",
    "not a robot",
    "you don't understand md",
)
_SERVICE_COMPLAINT_MARKERS = (
    "lagging",
    "was lagging",
    "support was lag",
    "answers were",
    "different line",
    "wrong line",
    "not helpful",
    "yesterday support",
)
_BYE_MARKERS = (
    "ok bye", "okay bye", "bye gagan", "bye bro", "good bye", "goodbye", "ok by",
    "thank you bye", "thanks bye", "ttyl",
)
_JOB_SEARCH_SERVICES = (
    "automation call process", "naukri profile creation", "resume building",
)
_INTERVIEW_MARKERS = (
    "interview support", "client round", "technical round", "internal round",
    "coding round", "have interview", "my interview", "interview tomorrow",
    "interview on", "interview at", "interview is",
)
_INTERVIEW_OR_EXAM_SCHEDULED_MARKERS = (
    "have interview", "have an interview", "i have interview", "got interview",
    "interview today", "interview tomorrow", "interview tonight", "interview on ",
    "interview at ", "interview is", "interview after", "interview in ", "interview right now",
    "my interview", "scheduled interview", "interview scheduled",
    "coding test", "technical assessment", "online assessment", "assessment scheduled",
    "have exam", "have an exam", "my exam", "exam today", "exam tomorrow",
    "exam on ", "exam at ", "proctored exam",
)
_SCHEDULING_PROOF_MARKERS = (
    "[photo]", "[document]", "[image]", "[media]", "screenshot", "screen shot",
    "confirmation mail", "interview confirmation", "calendar invite",
    "scheduling-refactoring", "meet.google", "codingtest.",
)
_INTERVIEW_SUPPORT_INTENT_MARKERS = (
    "interview support", "help me interview", "help with interview",
    "can you help me interview", "can you help interview", "help u interview",
    "need interview help", "assist interview", "for interview", "interview help",
    "help me with interview", "support for interview",
)
_ASK_ROUND_MARKERS = (
    "which round", "what round", "round is it for", "round type",
    "client round or technical", "client round aa technical", "round or technical",
)
_PROXY_CALL_MARKERS = (
    "proxy caller", "proxy callers", "proxy call", "proxy calls", "proxy interview",
    "proxy support", "interview proxy", "shadow caller", "shadow callers", "shadow call",
    "on behalf", "attend interview", "attend on my behalf", "attend for me",
    "someone to attend", "take my interview", "give interview for me",
    "attend interviews on behalf", "person who can attend",
)
_PROXY_DENIAL_MARKERS = (
    "we only provide live support", "only provide live support during",
    "not shadow caller", "not shadow callers", "don't provide shadow",
    "do not provide shadow", "cannot provide shadow", "can't provide shadow",
    "don't offer proxy", "we don't provide proxy", "do not offer proxy",
    "not proxy caller", "not proxy callers", "don't do proxy", "we don't do proxy",
    "cannot attend on your behalf", "can't attend on your behalf",
    "not attend on your behalf", "only live support during your",
    "not a proxy", "it's not a proxy", "it is not a proxy", "is not a proxy",
    "live interview support, not a proxy", "live support, not a proxy",
    "not shadow interview", "we don't attend", "do not attend on your behalf",
)

_USER_TELUGU_MARKERS = (
    "cheppandi", "cheyyandi", "chestham", "chestharu", "undhi", "undi", "meeku",
    "mee ", "epudu", "nenu", "miru", "meru", "kavali", "entha", "ayyindi",
    "unnava", "raakapothey", "telugu lo", "telugu language", "andhi", "broo",
    "ardam", "ledhu", "ledu", "appudu", "varaku", "ayyaka", "garu",
    "client round aa", "technical aa", "vishayam", "cheddam", "cheyachu",
)

_REPLY_TELUGU_MARKERS = _USER_TELUGU_MARKERS + (
    " ki ping", " side ", " clear ga ", "process clear ga",
)

# Longest-first phrase replacements when client writes English only.
_TELUGU_PHRASE_TO_ENGLISH = (
    (
        "calls raakapothey WhatsApp try cheyyandi — meeku em help kavali exactly cheppandi, connect chestham.",
        "If calls aren't coming, try WhatsApp — tell me exactly what help you need and we'll connect you.",
    ),
    (
        "Got it bro 👍 calls raakapothey WhatsApp try cheyyandi — meeku em help kavali exactly cheppandi, connect chestham.",
        "Got it bro 👍 if calls aren't coming, try WhatsApp — tell me exactly what help you need and we'll connect you.",
    ),
    ("client round aa technical aa?", "client round or technical?"),
    ("React noted — client round aa technical aa?", "React noted — client round or technical?"),
    ("payment ayyaka slot confirm chestham", "slot confirms after payment"),
    ("Tuesday ki ping cheyyandi", "ping me Tuesday"),
    ("Tuesday ping cheyyandi", "ping me Tuesday"),
    ("ready unte ping cheyyandi — appudu continue cheddam", "ping me when ready — we'll continue then"),
    ("interview support side continue cheddam", "let's continue with your interview support"),
    ("interview prep side continue cheddam — epudu undi mee round?", "let's continue interview prep — when is your round?"),
    ("mee tech stack cheppandi", "share your tech stack"),
    ("interview epudu undi?", "when is the interview?"),
    ("price & process explain chesa kada — ready unte Tuesday ki ping cheyyandi", "already shared price & process — ping me Tuesday when ready"),
    ("payment vishayam tarvata — mundu process clear ga discuss cheddam", "payment later — let's clarify the process first"),
    ("mee interview side focus cheddam", "let's focus on your interview"),
    ("meeku process & support step-by-step explain chestharu", "will explain process & support step-by-step"),
    ("meeku help chestharu", "will help you"),
    (" clear ga explain chestharu", " will explain clearly"),
    ("payment ayyaka ne slot confirm avutundi", "slot confirms only after payment"),
    ("Slot confirm cheyyadaniki mundu payment avvali — ready unte cheppandi", "Payment first before slot confirm — tell me when you're ready"),
    ("Lekapothey details ki ", "Otherwise for details "),
    (" garu help chestharu", " will help you"),
    (" garu (senior)", " (senior)"),
    (" garu (most senior", " (most senior"),
    (" garu / ", " / "),
    (" garu ", " "),
    (" garu,", ","),
    ("side ki ", "side — "),
    (" roles ki ", " roles — "),
    (" details ki ", " details — "),
    ("Deal close / detailed convincing ki ", "For closing the deal / detailed convincing — "),
    ("Sorry for confusion bro 👍 ", "Sorry for the confusion bro 👍 "),
    ("continue cheddam", "let's continue"),
    (" continue cheddam", " let's continue"),
    (" noted — ", " noted — "),
    (" aa ", " or "),
    (" ki ", " for "),
    (" cheppandi", ""),
    (" cheyyandi", ""),
    (" chestham", ""),
    (" chestharu", ""),
    ("undhi?", "?"),
    ("undi?", "?"),
)


def _user_only_blob(history: list[dict] | None, user_text: str, *, tail: int = 10) -> str:
    """User messages only — avoids assistant questions triggering volume/heuristics."""
    parts = [
        (m.get("content") or "")
        for m in (history or [])[-tail:]
        if (m.get("role") or "").lower() in ("user", "human", "client")
    ]
    parts.append(user_text or "")
    return " ".join(parts).lower()


def _user_messages(history: list[dict] | None, user_text: str = "") -> list[str]:
    msgs = [
        (m.get("content") or "").strip().lower()
        for m in (history or [])
        if (m.get("role") or "").lower() in ("user", "human", "client")
    ]
    if (user_text or "").strip():
        msgs.append((user_text or "").strip().lower())
    return msgs


def _parse_interview_time_from_blob(blob: str) -> str | None:
    """Parse H:MM AM/PM or plain H AM/PM — never treat minutes in 4:15PM as the hour."""
    b = (blob or "").lower()
    colon = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)\b", b)
    if colon:
        return f"{colon.group(1)}:{colon.group(2)} {colon.group(3).upper()}"
    plain = re.search(r"(?<![:\d])\b(\d{1,2})\s*(am|pm)\b", b)
    if plain:
        return f"{plain.group(1)} {plain.group(2).upper()}"
    return None


def _mine_round_type_from_user(history: list[dict] | None, user_text: str = "") -> str | None:
    """Round type from user messages only — latest answer wins (not assistant questions)."""
    for msg in reversed(_user_messages(history, user_text)):
        if msg in ("technical", "tech"):
            return "technical"
        if re.search(r"\btechnical\b", msg):
            return "technical"
        if msg in ("client",):
            return "client"
        if "technical round" in msg or "tech round" in msg:
            return "technical"
        if "technical with" in msg or "tech with" in msg:
            return "technical"
        if "client round" in msg or "client side" in msg:
            return "client"
        if "internal round" in msg:
            return "internal"
        if "coding round" in msg or "code round" in msg:
            return "coding"
        if "hr round" in msg:
            return "HR"
    return None


def _interview_support_service_needs(
    service: str,
    user_text: str,
    history: list[dict] | None,
) -> bool:
    if _user_offers_support_to_candidates(user_text, history):
        return False
    if service in (
        "interview support",
        "interview support till offer letter",
        "proxy interview support",
        "expert support provider",
    ):
        return service != "expert support provider"
    return _user_wants_interview_support(user_text, history)


_DEMO_INTEREST_MARKERS = (
    "go for demo", "go fro demo", "book the slot", "book slot", "want demo",
    "need demo", "connect with tech", "tech team", "will book", "definitely",
    "i'm interested", "im interested", "yes interested", "show me how",
    "how it works", "demo call", "demo timing", "demo time", "see how it works",
    "walk me through", "explain the process", "explain process",
)


def _stack_has_react(tech: str, history: list[dict] | None, user_text: str, qualification: dict | None) -> bool:
    if _is_react_frontend_domain(history, user_text, qualification):
        return True
    t = (tech or "").lower()
    return any(x in t for x in ("react", "mern", "frontend", "angular", "next"))


def _stack_has_java(tech: str, history: list[dict] | None, user_text: str, qualification: dict | None) -> bool:
    if _is_java_domain(history, user_text, qualification):
        return True
    t = (tech or "").lower()
    if "javascript" in t and "java" not in t.replace("javascript", ""):
        return False
    return "java" in t or "spring" in t


def _interview_tech_team_label(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None,
    *,
    tech: str = "",
) -> str:
    """Domain-routed tech team names for interview demo & support."""
    if _stack_has_react(tech, history, user_text, qualification) and _stack_has_java(
        tech, history, user_text, qualification,
    ):
        return f"{_staff.name('react_lead_b')} (React) & {_staff.name('senior_tech')} (Java)"
    if _is_data_analyst_domain(history, user_text, qualification):
        return _staff.name("data_lead")
    if _is_devops_domain(history, user_text, qualification):
        return _staff.name("devops_lead")
    if _stack_has_react(tech, history, user_text, qualification):
        return f"{_staff.name('react_lead_a')} / {_staff.name('react_lead_b')}"
    return _staff.name("senior_tech")


def _interview_fully_qualified(facts: dict, history: list[dict] | None, user_text: str) -> bool:
    tech = (facts.get("tech_stack") or "").strip()
    round_t = (facts.get("round_type") or "").strip()
    return bool(tech and round_t and _has_interview_timing_known(facts, history, user_text))


def _assistant_asked_demo_timing(history: list[dict] | None) -> bool:
    last = (_last_assistant_text(history) or "").lower()
    return any(
        p in last for p in (
            "demo call", "demo time", "time works", "pick a demo", "good time for demo",
            "when works for demo", "demo timing", "quick demo", "time suits you",
            "availability", "works best for your demo", "suit avtundi",
        )
    )


def _assistant_offered_demo(history: list[dict] | None) -> bool:
    last = (_last_assistant_text(history) or "").lower()
    return any(
        p in last for p in (
            "will demo", "give you a demo", "tech team demo", "demo how we",
            "demo first", "see how it works", "walk you through",
        )
    )


def _user_asks_demo_when(user_text: str, history: list[dict] | None) -> bool:
    """Client asking when the demo is — answer by asking THEIR availability."""
    t = (user_text or "").lower().strip()
    if not t:
        return False
    when_markers = (
        "when", "when?", "what time", "which time", "time?", "eppudu", "time entha",
        "demo when", "when demo", "when is demo", "when is the demo",
    )
    if not (t in ("when", "when?", "time?", "eppudu") or any(m in t for m in when_markers)):
        return False
    return _assistant_offered_demo(history) or _assistant_asked_demo_timing(history) or "demo" in t


def _user_gave_explicit_demo_timing(user_text: str, history: list[dict] | None) -> bool:
    """True only when the client stated a demo slot — not interview date alone."""
    t = (user_text or "").lower().strip()
    if not t:
        return False
    if any(m in t for m in (
        "demo at", "demo on", "for demo", "demo call at", "demo call on",
        "demo time", "demo ki", "demo today", "demo tomorrow", "for the demo",
        "quick demo at", "demo slot",
    )):
        return True
    if _assistant_asked_demo_timing(history):
        if _parse_interview_time_from_blob(t):
            return True
        for day in (
            "monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday", "tomorrow", "today", "evening", "morning",
        ):
            if day in t:
                return True
    return False


def _mine_demo_timing(history: list[dict] | None, user_text: str) -> str | None:
    """Demo slot time — only after client gives demo availability (not interview date)."""
    if not _user_gave_explicit_demo_timing(user_text, history):
        return None
    t = (user_text or "").lower()
    when = _parse_interview_time_from_blob(t)
    if when:
        return when
    for day in (
        "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday", "tomorrow", "today", "evening", "morning",
    ):
        if day in t:
            base = day.capitalize() if day not in ("evening", "morning") else day
            parsed = _parse_interview_time_from_blob(t)
            return f"{base} {parsed}".strip() if parsed else base
    return None


def _looks_premature_demo_schedule(
    reply_text: str,
    user_text: str,
    history: list[dict] | None,
) -> bool:
    """Demo time assumed or payment pushed before client shared demo availability."""
    if _user_confirmed_payment(user_text, history) or _user_ready_for_payment(user_text):
        return False
    lower = (reply_text or "").lower()
    if "demo" not in lower:
        return False
    if any(p in lower for p in (
        "what time works", "time suits you", "works best for you", "your availability",
        "when suits you", "demo call ki eppudu", "suit avtundi", "cheppandi — demo",
    )):
        return False
    if any(p in lower for p in (
        "right before", "just before", "before your interview", "before the interview",
        "scheduled right before", "can be scheduled right before",
    )):
        return True
    if (
        ("proceed with payment" in lower or "ready to proceed with payment" in lower)
        and not _user_gave_explicit_demo_timing(user_text, history)
        and (_user_asks_demo_when(user_text, history) or _assistant_offered_demo(history))
    ):
        return True
    return False


def _demo_availability_reply(
    *,
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    known = _known_facts_for_reply(history, qualification, user_text)
    known.pop("demo_timing", None)
    return _interview_support_smart_reply(
        known,
        history=history,
        user_text=user_text,
        qualification=qualification,
        lang=lang,
        lead=lead,
        force_ask_demo_availability=True,
    )


def _user_interested_in_demo(
    user_text: str,
    history: list[dict] | None,
    facts: dict,
) -> bool:
    if not _interview_fully_qualified(facts, history, user_text):
        return False
    t = (user_text or "").lower().strip()
    if _user_shows_purchase_interest(user_text) or _user_wants_demo(user_text):
        return True
    if any(m in t for m in _DEMO_INTEREST_MARKERS):
        return True
    if t in ("yes", "yeah", "yep", "ok", "okay", "sure", "fine", "done"):
        last = (_last_assistant_text(history) or "").lower()
        if any(w in last for w in ("interested", "demo", "how it works", "demo time")):
            return True
    return False


def _user_confirmed_payment(user_text: str, history: list[dict] | None) -> bool:
    blob = _user_only_blob(history or [], user_text, tail=12)
    return any(
        w in blob for w in (
            "paid", "payment done", "sent payment", "paid bro", "gpay chesa",
            "payment chesa", "amount sent", "transferred", "payment sent",
        )
    )


def _interview_support_smart_reply(
    facts: dict,
    *,
    history: list[dict] | None = None,
    user_text: str = "",
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
    prefix: str = "Got it 👍 ",
    force_ask_demo_availability: bool = False,
) -> str:
    """Contextual interview-support progression — tech team demo → timing → payment → slot."""
    # Caller should pass slot/user_id via _maybe_interview_exam_screenshot_reply at send time.
    if _is_data_analyst_domain(history, user_text, qualification):
        if (
            _user_asked_price_in_thread(history, user_text)
            or _user_ready_for_payment(user_text)
            or _user_shows_purchase_interest(user_text)
        ):
            return _vani_handoff_reply(
                empathy=_user_complains_repeat(user_text),
                reason="close_deal",
            )
        tech_early = (facts.get("tech_stack") or "").strip()
        if tech_early and _interview_fully_qualified(facts, history, user_text):
            return _vani_handoff_reply(reason="close_deal")

    en = lang == "english"
    addr = _addr_prefix(lead, lang) if lead else ""
    if (prefix or "").strip() in ("Got it 👍", "Got it 👍 "):
        prefix = _reply_ack_prefix(lead, lang, history=history)
    elif addr and prefix.startswith("Sorry"):
        prefix = f"Sorry {addr}my bad 👍 "

    tech = (facts.get("tech_stack") or "").strip()
    round_t = (facts.get("round_type") or "").strip()
    timing = (facts.get("interview_timing") or facts.get("deferral") or "").strip()
    team = _interview_tech_team_label(history, user_text, qualification, tech=tech)
    demo_timing = ""
    if _user_gave_explicit_demo_timing(user_text, history):
        demo_timing = (facts.get("demo_timing") or "").strip() or (_mine_demo_timing(history, user_text) or "")

    t = (user_text or "").lower()
    if any(m in t for m in ("recording", "listen to", "voice sample", "sample call", "hear them", "listed their")):
        contact = _senior_contact_line(history, user_text, qualification)
        if en:
            return (
                f"{prefix}{team} can share a sample call / voice clip so you can check English quality 👍 "
                f"{contact} — when is your first round?"
            )
        return (
            f"{prefix}{team} sample call / voice clip share chestharu — English quality check avtundi 👍 "
            f"{contact} — mee first round epudu?"
        )

    if _user_confirmed_payment(user_text, history):
        demo_bit = f" — demo at {demo_timing}" if demo_timing else ""
        if en:
            return (
                f"{prefix}payment received 👍 slot confirmed for {tech} {round_t} round "
                f"{timing}{demo_bit}. {team} will connect 👍"
            )
        return (
            f"{prefix}payment received 👍 {tech} {round_t} round {timing} slot confirm ayyindi"
            f"{demo_bit}. {team} connect avtaru 👍"
        )

    if (
        force_ask_demo_availability
        or _user_asks_demo_when(user_text, history)
        or (_user_interested_in_demo(user_text, history, facts) and not demo_timing)
    ) and not demo_timing:
        if en:
            return (
                f"{prefix}{team} from our tech team will run the demo for your {tech} "
                f"{round_t} round support. What date & time suits you for a short demo call? 👍"
            )
        return (
            f"{prefix}{team} tech team mee {tech} {round_t} round ki demo istharu. "
            f"Demo call ki meeku eppudu suit avtundi — date & time cheppandi 👍"
        )

    if _user_ready_for_payment(user_text) or (
        demo_timing and _should_quote_price(user_text, history)
    ):
        price_bit = " — round support ₹5000" if _should_quote_price(user_text, history) else ""
        if en:
            return (
                f"{prefix}{tech} {round_t} round {timing}{price_bit} — "
                f"share payment when ready, slot confirms right after 👍"
            )
        return (
            f"{prefix}{tech} {round_t} round {timing}{price_bit} — "
            f"payment chesaka slot confirm chestham 👍"
        )

    if demo_timing:
        if en:
            return (
                f"{prefix}demo at {demo_timing} noted — {team} will walk you through support "
                f"for your {tech} {round_t} round {timing}. Ready to proceed with payment? "
                f"Slot confirms after payment 👍"
            )
        return (
            f"{prefix}demo {demo_timing} noted — {team} mee {tech} {round_t} round {timing} "
            f"support explain chestharu. Payment ayyaka slot confirm 👍"
        )

    if _user_interested_in_demo(user_text, history, facts):
        if en:
            return (
                f"{prefix}{tech} {round_t} round {timing} — {team} from our tech team "
                f"will demo how we support you live. What time works for a quick demo call? 👍"
            )
        return (
            f"{prefix}{tech} {round_t} round {timing} — {team} tech team live ga "
            f"ela support chestamo demo istharu. Demo call ki eppudu suit avtundi? 👍"
        )

    if en:
        return (
            f"{prefix}{tech} {round_t} round {timing} noted — {team} handles demo & "
            f"live round support. Want to see how it works? Share a good demo time 👍"
        )
    return (
        f"{prefix}{tech} {round_t} round {timing} noted — {team} demo & live support "
        f"handle chestharu. Ela work avtundo chudadam ante demo time cheppandi 👍"
    )



def _detect_client_language(history: list[dict] | None, user_text: str) -> str:
    """english | telugu — mirror the client's language in replies."""
    blob = _user_only_blob(history, user_text)
    if any("\u0c00" <= c <= "\u0c7f" for c in blob):
        return "telugu"
    if any(m in blob for m in ("telugu language", "telugu lo", "talk in telugu", "in telugu")):
        return "telugu"
    if any(m in blob for m in _USER_TELUGU_MARKERS):
        return "telugu"
    return "english"


def _reply_contains_telugu(reply_text: str) -> bool:
    t = (reply_text or "").lower()
    if any("\u0c00" <= c <= "\u0c7f" for c in t):
        return True
    return any(m in t for m in _REPLY_TELUGU_MARKERS)


def _enforce_client_language(reply_text: str, lang: str) -> str:
    """If client writes English only, strip Telugu from our reply."""
    if lang != "english" or not (reply_text or "").strip():
        return reply_text
    out = reply_text
    for old, new in _TELUGU_PHRASE_TO_ENGLISH:
        if old in out:
            out = out.replace(old, new)
    # Collapse double spaces from removals
    while "  " in out:
        out = out.replace("  ", " ")
    out = out.replace(" — — ", " — ").replace("??", "?").strip()
    if _reply_contains_telugu(out):
        # Last resort: common tokens
        for tok in ("cheppandi", "cheyyandi", "chestham", "chestharu", "meeku", "garu", "epudu", "cheddam"):
            out = out.replace(tok, "")
        out = " ".join(out.split())
    return out.strip() or reply_text


def _vendor_partner_markers() -> tuple[str, ...]:
    return globals().get("_VENDOR_PARTNER_MARKERS") or ()


def _user_offers_support_to_candidates(
    user_text: str,
    history: list[dict] | None,
) -> bool:
    """Inbound expert wants to support OUR candidates — not seeking a job."""
    blob = _user_only_blob(history or [], user_text or "", tail=15)
    if any(m in blob for m in _PROVIDER_OFFERS_SUPPORT_MARKERS):
        return True
    if "provide" in blob and "support" in blob and "candidates" in blob:
        return True
    if "looking to provide" in blob and "support" in blob:
        return True
    if "job support opportunities" in blob and (
        "provide" in blob or "my support" in blob or "candidates who" in blob
    ):
        return True
    return False


def _provider_offers_on_job_task_support(
    user_text: str,
    history: list[dict] | None,
) -> bool:
    """Expert supports placed candidates on project/tasks — not interview rounds."""
    if not _user_offers_support_to_candidates(user_text, history):
        if not _user_offers_support_to_candidates("", history):
            return False
    blob = _conversation_blob(history or [], user_text or "", tail=24)
    if any(m in blob for m in _PROVIDER_ON_JOB_TASK_MARKERS):
        return True
    if "job support" in blob and "interview" in blob and "not interview" in blob:
        return True
    if "only job support" in blob or "only job support" in (user_text or "").lower():
        return True
    return False


def _user_is_vendor_partner(user_text: str, history: list[dict] | None) -> bool:
    """Recruiter/vendor offering candidates or asking for leads — NOT a job seeker."""
    if _user_offers_support_to_candidates(user_text, history):
        return True
    blob = _conversation_blob(history or [], user_text or "", tail=24)
    if any(m in blob for m in _vendor_partner_markers()):
        return True
    if "have a candidate" in blob or "have candidate" in blob:
        return True
    if "want candidate" in blob or "give me lead" in blob:
        return True
    if "1000" in blob and "closure" in blob:
        return True
    if "interviewer" in blob and ("not candidate" in blob or "not the candidate" in blob):
        return True
    return False


def _vendor_context_label(history: list[dict] | None, user_text: str) -> str:
    """Short tech/context snippet for vendor threads."""
    blob = _conversation_blob(history or [], user_text or "", tail=24)
    for label, keys in (
        ("ETL testing", ("etl testing", "etl test", "etl")),
        ("Power BI / SQL", ("power bi", "powerbi", "bi sql")),
        ("Wipro placement", ("wipro",)),
    ):
        if any(k in blob for k in keys):
            return label
    if "mnc" in blob:
        return "MNC placement"
    if "interview support" in blob or "support for interview" in blob:
        return "interview support"
    return "placement / candidates"


def _reply_looks_like_naukri_pitch(reply_text: str) -> bool:
    lower = (reply_text or "").lower()
    return any(x in lower for x in (
        "naukri", "not getting calls", "profile isn't ranking", "profile/resume isn't",
        "automation call", "search visibility boost", "resume help, or naukri",
        "interview support, resume help",
    ))


def _provider_shared_business_contact(user_text: str, history: list[dict] | None) -> bool:
    """Partner gave phone, WhatsApp, or email in the thread."""
    import re

    blob = _conversation_blob(history or [], user_text or "", tail=24)
    if re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", blob):
        return True
    if re.search(r"\b\d{10}\b", re.sub(r"\D", " ", blob)):
        return True
    if re.search(r"\+?\d{1,3}[\s-]?\d{10}", blob):
        return True
    lower = blob.lower()
    if any(m in lower for m in ("whatsapp", "whats app", "email", "mail id", "contact number")):
        if re.search(r"\d{8,}", blob):
            return True
    return False


def _provider_ask_business_contact(
    user_text: str,
    history: list[dict] | None,
    lead: dict | None,
) -> bool:
    """After stack is clear, ask for WhatsApp/email if missing (data room, not Telegram)."""
    if _provider_shared_business_contact(user_text, history):
        return False
    known = _known_facts_for_reply(history, None, user_text)
    tech = (known.get("tech_stack") or "").strip()
    if not tech:
        return False
    blob = _conversation_blob(history or [], user_text or "", tail=20)
    if _provider_offers_on_job_task_support(user_text, history) or "provide" in blob:
        return True
    return _user_offers_support_to_candidates(user_text, history)


def _support_provider_inbound_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Expert offers Java/React/etc. support for our candidates — not a job seeker."""
    en = lang == "english"
    addr = _addr_prefix(lead, lang)
    known = _known_facts_for_reply(history, qualification, user_text)
    tech = (known.get("tech_stack") or "").strip()
    on_job = _provider_offers_on_job_task_support(user_text, history)
    ask_contact = _provider_ask_business_contact(user_text, history, lead)
    if _provider_shared_business_contact(user_text, history):
        if en:
            return (
                f"Thanks {addr}👍 contact noted for our partner data room — "
                f"our team will reach out when we have candidate volume 👍"
            )
        return (
            f"Thanks {addr}👍 contact noted — volume ready ayyaka team reach avtaru 👍"
        )
    if _user_wants_phone_call(user_text, history):
        return _vendor_call_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        )
    if ask_contact:
        if en:
            return (
                f"Got it {addr}👍 noted for our partner data room. "
                f"Please share your WhatsApp number or email (we keep business contact there — "
                f"not Telegram) so we can reach you when bench volume is ready 👍"
            )
        return (
            f"Got it {addr}👍 partner data room lo save chestham — "
            f"WhatsApp number or email share cheyyandi (Telegram kadu) volume ready ayyaka reach avtam 👍"
        )
    if on_job:
        if en:
            if tech:
                return (
                    f"Got it {addr}👍 you provide {tech} on-the-job project/task support "
                    f"for our placed candidates (not interview rounds, not a job for yourself) — "
                    f"we align bench experts when volume is high. "
                    f"Share your WhatsApp or email for our partner records 👍"
                )
            return (
                f"Got it {addr}👍 on-the-job project/task support for our candidates "
                f"(not interview rounds) — which tech stack? Then WhatsApp or email for our data room 👍"
            )
        if tech:
            return (
                f"Got it {addr}👍 mee candidates ki {tech} on-job project/task support "
                f"(interview rounds kadhu) — WhatsApp or email share cheyyandi data room ki 👍"
            )
        return (
            f"Got it {addr}👍 on-job project/task support — tech stack enti? "
            f"WhatsApp or email kuda share cheyyandi 👍"
        )
    if en:
        if tech:
            return (
                f"Got it {addr}👍 you provide {tech} support for our candidates "
                f"(not a job for yourself) — we work with experts when volume is high. "
                f"Share WhatsApp or email for our partner data room 👍"
            )
        return (
            f"Got it {addr}👍 partnership noted — which tech stack? "
            f"WhatsApp or email for our data room 👍"
        )
    if tech:
        return (
            f"Got it {addr}👍 {tech} support provide chestharu — "
            f"WhatsApp or email share cheyyandi data room ki 👍"
        )
    return (
        f"Got it {addr}👍 partnership side — tech stack + WhatsApp or email share cheyyandi 👍"
    )


def _vendor_partner_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
    small_talk: bool = False,
) -> str:
    """Partnership / candidate-supply inbound — never Naukri job-seeker scripts."""
    if _user_offers_support_to_candidates(user_text, history):
        return _support_provider_inbound_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        )
    en = lang == "english"
    addr = _addr_prefix(lead, lang)
    phone = _call_senior_phone_only(history, user_text, qualification, lang=lang)
    ctx = _vendor_context_label(history, user_text)

    if _user_wants_phone_call(user_text, history):
        return _vendor_call_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        )

    if small_talk:
        if en:
            return f"All good {addr}👍 About the {ctx} we discussed — partnership or round support?"
        return f"All good {addr}👍 {ctx} side — partnership na round support na?"

    if en:
        return f"Got it {addr}👍 {ctx} noted — partnership deal or live round support?"
    return f"Got it {addr}👍 {ctx} — partnership deal na round support na?"


def _user_wants_job_search_support(user_text: str, history: list[dict] | None) -> bool:
    """Naukri / resume / calls — NOT interview support. User messages only."""
    if _user_is_vendor_partner(user_text, history):
        return False
    intent = resolve_thread_intent(history, user_text)
    if intent_blocks_job_search(intent):
        return False
    if _user_wants_interview_support(user_text, history):
        return False
    blob = _user_only_blob(history or [], user_text, tail=20)
    if _user_wants_job_help(user_text, history):
        return True
    if _user_wants_resume_documents(user_text, history):
        return True
    if any(m in blob for m in _AUTOMATION_CALL_MARKERS):
        return True
    if any(m in blob for m in _NAUKRI_PROFILE_MARKERS):
        return True
    if any(m in blob for m in _RESUME_BUILDING_MARKERS):
        return True
    if "naukri" in blob and any(w in blob for w in ("call", "calls", "resume", "profile", "upload")):
        return True
    if any(w in blob for w in ("looking for a job", "looking for job", "need a job", "job search")):
        if not any(w in blob for w in _INTERVIEW_MARKERS):
            if "naukri" in blob or any(m in blob for m in _AUTOMATION_CALL_MARKERS):
                return True
    return False


def _user_wants_resume_documents(user_text: str, history: list[dict] | None) -> bool:
    blob = _conversation_blob(history or [], user_text)
    if any(m in blob for m in _DOCUMENT_RESUME_MARKERS):
        return True
    if "document" in blob and "resume" in blob:
        return True
    if "documents" in blob and any(w in blob for w in ("resume", "experience", "company", "keep")):
        return True
    return False


def _user_interview_not_scheduled(user_text: str, history: list[dict] | None) -> bool:
    blob = _conversation_blob(history or [], user_text)
    return any(m in blob for m in _INTERVIEW_NOT_SCHEDULED_MARKERS)


def _user_low_signal(user_text: str) -> bool:
    t = (user_text or "").strip()
    if not t:
        return True
    if t in (".", "..", "...", "…", "...."):
        return True
    return len(t) <= 2 and all(c in ".,!?;:'\"" for c in t)


def _resume_document_reply(
    user_text: str,
    *,
    history: list[dict] | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    blob = _conversation_blob(history or [], user_text)
    addr = _addr_prefix(lead, lang)
    en = lang == "english"

    if any(w in blob for w in (
        "experience doc", "experience letter", "experience certificate",
        "relieving", "employment doc", "company doc",
    )):
        if en:
            return (
                f"Got it {addr}👍 for experience docs we need company name, role, dates & "
                f"2–3 project points — we'll format them on your resume. How many companies?"
            )
        return (
            f"Got it {addr}👍 experience docs ki company, role, dates & project points kavali — "
            f"resume lo align chestham. Enni companies?"
        )

    if en:
        return (
            f"Got it {addr}👍 yes — we help with resume documents & ATS formatting. "
            f"Fresh resume or updating your existing one with experience docs?"
        )
    return (
        f"Got it {addr}👍 resume documents & ATS formatting help chestham. "
        f"Fresh resume na existing resume update na?"
    )


def _job_search_service_reply(
    history: list[dict] | None,
    user_text: str,
    *,
    lang: str = "english",
    prefix: str = "Got it bro 👍 ",
    include_price: bool = False,
    lead: dict | None = None,
) -> str:
    """Value-first for Naukri / resume / call automation — price only when asked."""
    if _user_requests_india_job_support(user_text, history):
        return _india_no_job_support_reply(lang=lang, lead=lead)
    blob = _user_only_blob(history or [], user_text, tail=20)
    en = lang == "english"

    if any(m in blob for m in _AUTOMATION_CALL_MARKERS) or (
        "naukri" in blob and any(w in blob for w in ("call", "calls", "not getting"))
    ):
        if include_price:
            if en:
                return (
                    f"{prefix}Automation Call package ₹15k — resume rewrite + call automation + "
                    f"search visibility so recruiters find you. Naukri profile optimization alone ₹5k. "
                    f"Which fits your situation?"
                )
            return (
                f"{prefix}Automation Call package ₹15k — resume + call automation + search visibility. "
                f"Profile optimization alone ₹5k. Edi kavali?"
            )
        if en:
            return (
                f"{prefix}usually profile visibility is the issue 👍 "
                f"We help with resume + profile optimization. What's your experience level?"
            )
        return (
            f"{prefix}mostly profile visibility issue 👍 "
            f"Resume + profile optimization help chestham. Experience entha?"
        )

    if "naukri" in blob:
        if include_price:
            if en:
                return (
                    f"{prefix}Naukri Profile Creation & optimization ₹5k — full setup + keyword "
                    f"optimization so recruiters find you. Want to proceed?"
                )
            return f"{prefix}Naukri Profile Creation & optimization ₹5k — setup + optimize chestham. Proceed avvala?"
        if en:
            return (
                f"{prefix}we create and optimize your Naukri profile — keywords, headline, skills — "
                f"so recruiters find you when they search. Do you already have a profile or starting fresh?"
            )
        return (
            f"{prefix}Naukri profile create + optimize chestham — keywords, headline, skills — "
            f"recruiters search lo kanipovadaniki. Profile undha already leda fresh start?"
        )

    if any(m in blob for m in _RESUME_BUILDING_MARKERS):
        if include_price:
            if en:
                return (
                    f"{prefix}Resume Building ₹5k — we create/update your resume as per your profile. "
                    f"Share your experience?"
                )
            return (
                f"{prefix}Resume Building ₹5k — mee profile & experience batti resume create/update chestham. "
                f"Experience cheppandi?"
            )
        if en:
            return (
                f"{prefix}we build/update your resume based on your profile — ATS-friendly so it passes "
                f"screening and gets you more callbacks. What's your tech stack and experience?"
            )
        return (
            f"{prefix}mee profile batti ATS-friendly resume create/update chestham — screening pass avvadaniki. "
            f"Tech stack & experience cheppandi?"
        )

    if include_price:
        if en:
            return (
                f"{prefix}what exactly do you need — Resume Building ₹5k, "
                f"Naukri Profile ₹5k, or Automation Call package ₹15k?"
            )
        return (
            f"{prefix}emi kavali — Resume Building ₹5k, Naukri Profile ₹5k, "
            f"leda Automation Call package ₹15k?"
        )
    if en:
        return (
            f"{prefix}we help with resume building, Naukri profile setup, or full call automation "
            f"if calls aren't coming — depends on what's blocking you. What's the main issue right now?"
        )
    return (
        f"{prefix}resume, Naukri profile, leda calls automation help chestham — mee problem enti mainly?"
    )


def _user_names_abroad_region_only(user_text: str, history: list[dict] | None) -> bool:
    """Short reply naming a foreign market (e.g. 'Europe / UK')."""
    t = (user_text or "").strip().lower()
    if not t or len(t) > 80:
        return False
    if not _user_thread_targets_abroad(history, user_text):
        return False
    if _user_wants_interview_support(user_text, history):
        return False
    compact = re.sub(r"[^a-z0-9/+\s]", " ", t)
    compact = re.sub(r"\s+", " ", compact).strip()
    short_regions = {
        "europe", "uk", "europe uk", "europe / uk", "usa", "us", "canada",
        "australia", "dubai", "uae", "singapore", "germany",
    }
    return compact in short_regions or any(compact == m for m in _ABROAD_REGION_MARKERS if len(m) < 20)


def _enforce_job_search_service(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    lang: str = "english",
) -> str:
    """Don't pitch interview support when client wants Naukri/resume/call help."""
    if _user_thread_targets_abroad(history, user_text):
        return _abroad_job_policy_reply(user_text, history=history, lang=lang)
    if not _user_wants_job_search_support(user_text, history):
        if _user_is_vendor_partner("", history) and _reply_looks_like_naukri_pitch(reply_text):
            return _vendor_partner_reply(
                user_text, history=history, lang=lang,
            )
        return reply_text
    lower = (reply_text or "").lower()
    wrong = any(x in lower for x in (
        "1.8", "offer letter", "till offer", "initial ₹20", "initial 20k", "initial ₹20k",
        "client round", "technical round", "interview prep", "live round assistance",
        "per interview", "slot confirm",
    ))
    asks_interview_round = any(p in lower for p in _ASK_TECH_MARKERS) and any(
        w in lower for w in ("client round", "technical round", "round or")
    )
    if wrong or asks_interview_round or _reply_looks_like_naukri_pitch(reply_text):
        return _job_search_service_reply(
            history, user_text, lang=lang,
            include_price=_should_quote_price(user_text, history),
        )
    return reply_text


def _enforce_interview_support_service(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Never pitch Naukri/resume/menu when thread is interview support."""
    if _user_offers_support_to_candidates(user_text, history):
        return _support_provider_inbound_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        )
    known = _known_facts_for_reply(history, qualification, user_text)
    service = (known.get("service_need") or "").strip()
    if not _interview_support_service_needs(service, user_text, history):
        return reply_text
    lower = (reply_text or "").lower()
    weak_closure = (
        _interview_fully_qualified(known, history, user_text)
        and (
            "slot confirms after payment" in lower
            or "payment ayyaka slot confirm" in lower
        )
        and not any(n in lower for n in ("bhavana", "thirlok", "nikhila", "demo call", "what time"))
    )
    team_label = _interview_tech_team_label(
        history, user_text, qualification, tech=(known.get("tech_stack") or ""),
    ).lower()
    team_names = {
        p.strip().split("(")[0].strip().split()[0]
        for p in re.split(r"[/&]", team_label) if p.strip()
    }
    missing_team = (
        _interview_fully_qualified(known, history, user_text)
        and team_names
        and not any(n.lower() in lower for n in team_names if len(n) > 2)
    )
    if not (
        _reply_looks_like_naukri_pitch(reply_text)
        or _looks_generic_assistant(reply_text)
        or "resume help" in lower
        or weak_closure
        or missing_team
        or (_user_interested_in_demo(user_text, history, known) and "demo" not in lower)
        or (_mine_demo_timing(history, user_text) and "payment" not in lower)
    ):
        return reply_text
    contextual = _reply_from_known_facts(
        known,
        lang=lang,
        history=history,
        user_text=user_text,
    )
    if contextual:
        return contextual
    if _interview_fully_qualified(known, history, user_text):
        return _interview_support_smart_reply(
            known,
            history=history,
            user_text=user_text,
            qualification=qualification,
            lang=lang,
            lead=lead,
        )
    addr = _addr_prefix(lead, lang)
    tech = (known.get("tech_stack") or "").strip()
    if tech:
        if lang == "english":
            return f"Got it {addr}👍 {tech} interview support — {_tech_team_demo_phrase_short(lang)} 👍"
        return f"Got it {addr}👍 {tech} interview support — {_tech_team_demo_phrase_short(lang)} 👍"
    if lang == "english":
        return f"Got it {addr}👍 interview support — which tech stack? 👍"
    return f"Got it {addr}👍 interview support — mee tech stack cheppandi 👍"


def _value_first_interview_reply(
    user_text: str,
    history: list[dict] | None,
    *,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    """Explain how interview support works — no price unless asked."""
    if _user_wants_proxy_call(user_text, history):
        return _proxy_call_service_reply(
            user_text, history=history, lang=lang, lead=lead,
        )
    en = lang == "english"
    if _user_wants_interview_till_offer(user_text, history):
        if en:
            return (
                "Got it bro 👍 interview support till offer letter means we stay with you through "
                f"every round — {_tech_team_demo_phrase(lang)} through all rounds till offer letter. "
                "Which tech stack?"
            )
        return (
            f"Got it bro 👍 offer letter varaku anni rounds lo {_tech_team_demo_phrase_short(lang)}. "
            "Tech stack cheppandi?"
        )
    if en:
        return (
            f"Got it bro 👍 we provide interview support — {_tech_team_demo_phrase(lang)}. "
            "Which tech stack? Share a screenshot of your interview invite or confirmation here 👍"
        )
    return (
        f"Got it bro 👍 interview support untundi — {_tech_team_demo_phrase(lang)}. "
        "Tech stack + interview invite screenshot share cheyyandi 👍"
    )


def _enforce_value_before_price(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None = None,
    lang: str = "english",
) -> str:
    """Don't dump prices unless user asked or shows buy interest — explain value first."""
    if _is_data_analyst_domain(history, user_text, qualification) and _reply_has_pricing(reply_text):
        return _vani_handoff_reply(
            empathy=_user_complains_repeat(user_text),
            reason="close_deal" if _user_asked_price_in_thread(history, user_text) else "process",
        )
    if _should_quote_price(user_text, history, qualification):
        return reply_text
    if not _reply_has_pricing(reply_text):
        return reply_text
    if _user_wants_job_search_support(user_text, history):
        return _job_search_service_reply(
            history, user_text, lang=lang, include_price=False,
        )
    lower = (reply_text or "").lower()
    if any(x in lower for x in (
        "interview", "offer letter", "client round", "technical round", "job support",
    )):
        return _value_first_interview_reply(user_text, history, lang=lang)
    return reply_text


def _user_wants_interview_support(user_text: str, history: list[dict] | None = None) -> bool:
    if _user_offers_support_to_candidates(user_text, history):
        return False
    blob = _conversation_blob(history or [], user_text, tail=20)
    if any(m in blob for m in _INTERVIEW_SUPPORT_INTENT_MARKERS):
        return True
    if "interview" in blob and any(w in blob for w in ("help", "support", "assist", "looking for")):
        return True
    return False


def _has_interview_timing_known(facts: dict, history: list[dict] | None, user_text: str) -> bool:
    timing = (facts.get("interview_timing") or facts.get("deferral") or "").strip().lower()
    if timing in ("not scheduled yet", "no interview date yet"):
        return True
    if (facts.get("interview_timing") or facts.get("deferral") or "").strip():
        return True
    if _user_interview_not_scheduled(user_text, history):
        return True
    blob = _conversation_blob(history or [], user_text, tail=20)
    if any(w in blob for w in (
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "tomorrow", "today", " am", " pm", "morning", "evening", "next week",
    )):
        return True
    import re
    if re.search(r"\b\d{1,2}[:./]\d{2}\b", blob) or re.search(r"\b\d{1,2}\s*(am|pm)\b", blob):
        return True
    return False


def _user_inquiring_about_our_services(
    user_text: str,
    history: list[dict] | None = None,
) -> bool:
    """Responded to our ad / asking charges or experience terms — not scheduling a round."""
    blob = _user_only_blob(history or [], user_text, tail=10)
    if any(
        m in blob
        for m in (
            "saw your ad",
            "your charges",
            "your charge",
            "how many years",
            "years we can show",
            "show experience",
            "fee after interview",
            "placement fee",
            "call you after",
            "i'll call you",
            "i ll call you",
            "will call you",
        )
    ):
        return True
    if _is_price_inquiry(user_text):
        return True
    for m in (history or []):
        if (m.get("role") or "").lower() in ("user", "human", "client"):
            if _is_price_inquiry(m.get("content") or ""):
                return True
    return False


def _user_pasted_outbound_marketing(user_text: str, history: list[dict] | None) -> bool:
    """Lead pasted our (or similar) promo blurb — not their own interview schedule."""
    blob = _user_only_blob(history or [], user_text, tail=6)
    hits = sum(
        1
        for m in (
            "power bi & data analyst",
            "fee after interview placement",
            "recruitment ha",
            "interview support. recruitment",
            _staff.phone_digits("data_lead"),
        )
        if m in blob
    )
    return hits >= 2


def _user_claims_interview_or_exam_scheduled(
    user_text: str,
    history: list[dict] | None = None,
) -> bool:
    """Client says an interview or exam is scheduled / imminent."""
    if _user_interview_not_scheduled(user_text, history):
        return False
    if _user_inquiring_about_our_services(user_text, history):
        return False
    if _user_pasted_outbound_marketing(user_text, history):
        return False
    user_blob = _user_only_blob(history or [], user_text, tail=5)
    if any(m in user_blob for m in _INTERVIEW_OR_EXAM_SCHEDULED_MARKERS):
        return True
    if "interview" in user_blob and any(
        w in user_blob
        for w in (
            "today", "tomorrow", "tonight", "scheduled", "have",
            "after 1 hour", "1 hour", "right now",
        )
    ):
        return True
    recent = _user_only_blob(history or [], user_text, tail=3)
    if "interview" in recent and any(
        w in recent
        for w in (
            "monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday", "now",
        )
    ):
        if not _user_pasted_outbound_marketing(user_text, history):
            return True
    if any(w in user_blob for w in ("coding test", "technical assessment", "online exam")):
        if any(w in user_blob for w in ("help", "support", "have", "today", "now", "plz", "please")):
            return True
    return False


def _thread_has_scheduling_proof(
    slot: str,
    user_id: int,
    history: list[dict] | None,
    user_text: str,
) -> bool:
    blob = _conversation_blob(history or [], user_text)
    if any(m in blob for m in _SCHEDULING_PROOF_MARKERS):
        return True
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    for m in conv.get("messages") or []:
        if m.get("direction") != "in":
            continue
        mt = (m.get("media_type") or "").lower()
        if mt in ("photo", "document", "image"):
            return True
        text = (m.get("text") or "").strip().lower()
        if text in ("[photo]", "[document]", "[image]", "[media]"):
            return True
    return False


def _assistant_asked_scheduling_screenshot(history: list[dict] | None) -> bool:
    for m in reversed(history or []):
        role = (m.get("role") or "").lower()
        if role not in ("assistant",):
            continue
        c = (m.get("content") or "").lower()
        if "screenshot" in c and any(
            x in c for x in ("interview", "exam", "invite", "confirmation", "schedule", "assessment")
        ):
            return True
    return False


def _user_mentions_exam_not_interview(user_text: str, history: list[dict] | None) -> bool:
    blob = _user_only_blob(history or [], user_text, tail=10)
    if "interview" in blob and "exam" not in blob and "assessment" not in blob:
        return False
    return any(
        w in blob for w in ("exam", "assessment", "proctor", "coding test", "codingtest")
    )


def _interview_exam_screenshot_request_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    known = _known_facts_for_reply(history, qualification, user_text)
    tech = (known.get("tech_stack") or "").strip()
    addr = _addr_prefix(lead, lang)
    en = lang == "english"
    exam = _user_mentions_exam_not_interview(user_text, history) or _user_asks_proctoring(
        user_text, history,
    )
    if exam:
        if en:
            return (
                f"Got it {addr}👍 please share a screenshot of your exam / assessment "
                f"invite or scheduling page here 👍"
            )
        return (
            f"Got it {addr}👍 exam / assessment invite or schedule screenshot "
            f"share cheyyandi 👍"
        )
    if tech:
        if en:
            return (
                f"Got it {addr}👍 {tech} noted — please share a screenshot of your "
                f"interview invite or confirmation mail here 👍"
            )
        return (
            f"Got it {addr}👍 {tech} — interview invite or confirmation mail "
            f"screenshot share cheyyandi 👍"
        )
    if en:
        return (
            f"Got it {addr}👍 please share a screenshot of your interview or exam "
            f"invite / confirmation here 👍"
        )
    return (
        f"Got it {addr}👍 interview leda exam invite / confirmation screenshot "
        f"share cheyyandi 👍"
    )


def _maybe_interview_exam_screenshot_reply(
    slot: str,
    user_id: int,
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str | None:
    if _user_inquiring_about_our_services(user_text, history):
        return None
    if _is_data_analyst_domain(history, user_text, qualification):
        if _user_asked_price_in_thread(history, user_text) or _user_inquiring_about_our_services(
            user_text, history,
        ):
            return None
    if not _user_claims_interview_or_exam_scheduled(user_text, history):
        return None
    if _thread_has_scheduling_proof(slot, user_id, history, user_text):
        return None
    return _interview_exam_screenshot_request_reply(
        user_text,
        history=history,
        qualification=qualification,
        lang=lang,
        lead=lead,
    )


def _enforce_interview_exam_screenshot(
    reply_text: str,
    user_text: str,
    *,
    slot: str = "",
    user_id: int = 0,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    if not slot or not user_id:
        return reply_text
    forced = _maybe_interview_exam_screenshot_reply(
        slot,
        int(user_id),
        user_text,
        history=history,
        qualification=qualification,
        lang=lang,
        lead=lead,
    )
    if not forced:
        return reply_text
    lower = (reply_text or "").lower()
    if "screenshot" in lower and any(
        x in lower for x in ("interview", "exam", "invite", "confirmation", "assessment")
    ):
        return reply_text
    return forced


def _interview_timing_question(
    tech: str,
    *,
    lang: str = "english",
    prefix: str = "Got it 👍 ",
    ask_screenshot: bool = False,
) -> str:
    if lang == "english":
        if ask_screenshot:
            return (
                f"{prefix}{tech} noted — please share a screenshot of your interview "
                f"invite or confirmation mail here, and your date & time 👍"
            )
        return f"{prefix}{tech} noted — when is your interview date & time? 👍"
    if ask_screenshot:
        return (
            f"{prefix}{tech} noted — interview invite/confirmation screenshot + "
            f"date & time cheppandi 👍"
        )
    return f"{prefix}{tech} noted — interview date & time cheppandi? 👍"


def _enforce_interview_timing_first(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "english",
) -> str:
    """Tech known + interview support → ask date/time BEFORE round type."""
    if _user_wants_resume_documents(user_text, history):
        return reply_text
    if _user_interview_not_scheduled(user_text, history):
        return reply_text
    if _user_wants_interview_till_offer(user_text, history):
        return reply_text
    lower = (reply_text or "").lower()
    if any(x in lower for x in ("1.8", "till offer", "offer letter", "initial payment", "initial ₹20")):
        return reply_text
    known = _known_facts_for_reply(history, qualification, user_text)
    tech = (known.get("tech_stack") or "").strip()
    if not tech or _has_interview_timing_known(known, history, user_text):
        return reply_text
    service = (known.get("service_need") or "").strip()
    if not (
        service in ("interview support", "interview support till offer letter", "proxy interview support")
        or _user_wants_interview_support(user_text, history)
    ):
        return reply_text
    asks_round_early = any(m in lower for m in _ASK_ROUND_MARKERS) or (
        "round" in lower and "interview" in lower and "when" not in lower
    )
    if asks_round_early:
        prefix = "Got it bro 👍 " if "bro" in lower else "Got it 👍 "
        need_shot = _user_claims_interview_or_exam_scheduled(user_text, history)
        return _interview_timing_question(
            tech, lang=lang, prefix=prefix, ask_screenshot=need_shot,
        )
    return reply_text


def _user_wants_interview_till_offer(user_text: str, history: list[dict] | None) -> bool:
    blob = _conversation_blob(history or [], user_text)
    if any(m in blob for m in _JOB_SUPPORT_MARKERS):
        return False
    return any(m in blob for m in _OFFER_LETTER_MARKERS)


def _enforce_pricing_rules(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
) -> str:
    """Interview till offer letter = 1.8L (initial 20k). Never quote Job Support 35k for that."""
    if not _user_wants_interview_till_offer(user_text, history):
        return reply_text
    lower = (reply_text or "").lower()
    wrong = (
        any(x in lower for x in ("35,000", "35000", "35k", "₹35", "35,000"))
        or "job support" in lower
    )
    if not wrong:
        return reply_text
    if _should_quote_price(user_text, history):
        lang = _detect_client_language(history, user_text)
        return (
            "Interview support till offer letter is ₹1.8 Lakhs bro 👍 initial payment ₹20k — "
            f"{_tech_team_demo_phrase_short(lang)} through all rounds till offer letter. Which tech stack?"
        )
    return _value_first_interview_reply(user_text, history)


def _mine_conversation_facts(history: list[dict], user_text: str = "") -> dict:
    """Scan the full thread for facts the LLM may have missed or forgotten."""
    user_blob = _user_only_blob(history or [], user_text, tail=40)
    full_blob = " ".join((m.get("content") or "") for m in (history or [])).lower()
    if (user_text or "").strip():
        full_blob = f"{full_blob} {(user_text or '').lower()}".strip()
    facts: dict = {}

    intent = resolve_thread_intent(history or [], user_text)
    facts["thread_intent"] = intent
    sn = service_need_for_intent(intent)
    if sn:
        facts["service_need"] = sn
    if intent == INTENT_DEV_COLLAB:
        facts["thread_type"] = "dev_collaboration_inbound"

    if any(m in user_blob for m in _AUTOMATION_CALL_MARKERS) or (
        "naukri" in user_blob and any(w in user_blob for w in ("call", "calls", "not getting", "no call"))
    ):
        facts["service_need"] = "automation call process"
    elif any(m in user_blob for m in _NAUKRI_PROFILE_MARKERS):
        facts["service_need"] = "naukri profile creation"
    elif any(m in user_blob for m in _JOB_SEEKER_MARKERS):
        facts["service_need"] = "job support"
    elif any(m in user_blob for m in _RESUME_BUILDING_MARKERS):
        facts["service_need"] = "resume building"
    elif _user_wants_resume_documents("", history or []):
        facts["service_need"] = "resume building"
    elif "naukri" in user_blob and "resume" in user_blob:
        facts["service_need"] = "automation call process"

    if any(m in user_blob for m in _PROXY_CALL_MARKERS):
        facts["service_need"] = "proxy interview support"

    if _user_offers_support_to_candidates(user_text, history or []):
        facts["service_need"] = "expert support provider"
        facts["thread_type"] = "support_provider_inbound"
        if _provider_offers_on_job_task_support(user_text, history or []):
            facts["provider_mode"] = "on_job_tasks"
            facts["service_need"] = "on-job expert support provider"

    if not facts.get("service_need") and any(m in user_blob for m in _INTERVIEW_SUPPORT_INTENT_MARKERS):
        facts["service_need"] = "interview support"

    if not facts.get("service_need") and any(w in user_blob for w in _INTERVIEW_MARKERS):
        facts["service_need"] = "interview support"
    elif not facts.get("service_need") and "interview" in user_blob:
        facts["service_need"] = "interview support"

    if _user_wants_interview_till_offer("", history or []):
        facts["service_need"] = "interview support till offer letter"
    elif any(m in full_blob for m in _JOB_SUPPORT_MARKERS):
        facts["service_need"] = "job support"

    techs: list[str] = []
    for needle, label in _TECH_DETECT:
        if _tech_needle_in_blob(needle, user_blob) or _tech_needle_in_blob(needle, full_blob):
            if label not in techs:
                techs.append(label)
    if techs:
        facts["tech_stack"] = " + ".join(techs)

    round_t = _mine_round_type_from_user(history or [], user_text)
    if round_t:
        facts["round_type"] = round_t

    if not facts.get("interview_timing"):
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "tomorrow"):
            if day in user_blob:
                facts["interview_timing"] = day.capitalize()
                break
    when = _parse_interview_time_from_blob(user_blob)
    if when:
        base = (facts.get("interview_timing") or "").strip()
        facts["interview_timing"] = f"{base} {when}".strip() if base else when
    demo_when = _mine_demo_timing(history or [], user_text)
    if demo_when:
        facts["demo_timing"] = demo_when
    if "morning" in user_blob and facts.get("interview_timing"):
        if "morning" not in str(facts["interview_timing"]).lower():
            facts["interview_timing"] = f"{facts['interview_timing']} morning"
    if any(m in user_blob for m in _INTERVIEW_NOT_SCHEDULED_MARKERS):
        facts["interview_timing"] = "not scheduled yet"
        facts["urgency"] = "no interview date yet"

    if "tuesday" in user_blob:
        facts["deferral"] = "Tuesday"
        facts["urgency"] = "deferred — ping Tuesday"

    if any(w in user_blob for w in ("fresher", "0-2", "0 to 2", "2 years", "3 years", "5 years", "experienced")):
        if "fresher" in user_blob:
            facts["experience"] = "fresher"
        elif any(w in user_blob for w in ("5 year", "5+")):
            facts["experience"] = "5+y"

    if any(m in full_blob for m in _DATA_ANALYST_MARKERS):
        facts["domain"] = "data_analyst"
    elif any(m in full_blob for m in _AI_ML_MARKERS):
        facts["domain"] = "ai_ml"
    elif _blob_has_java(full_blob) or any(label in techs for label in ("Java", "Spring")):
        facts["domain"] = "java"
    elif any(m in full_blob for m in _DEVOPS_MARKERS) or "devops" in full_blob:
        facts["domain"] = "devops"
    elif any(label in techs for label in ("DevOps", "AWS")):
        facts["domain"] = "devops"
    elif any(m in full_blob for m in _REACT_FRONTEND_MARKERS):
        facts["domain"] = "react_frontend"
    elif any(
        t in full_blob
        for t in ("react", "mern", "next.js", "nextjs", "frontend")
    ) and any(t in full_blob for t in ("full stack", "fullstack", "full-stack")):
        facts["domain"] = "react_frontend"
    elif any(label in techs for label in ("React", "MERN")):
        facts["domain"] = "react_frontend"

    return facts


def _blob_has_java(blob: str) -> bool:
    if any(m in blob for m in _JAVA_MARKERS):
        return True
    if "java" not in blob:
        return False
    if "javascript" in blob and "java developer" not in blob and "spring" not in blob:
        if not any(x in blob for x in ("+ java", "java +", "java backend", "java full")):
            return False
    return True


def _merge_qualification(stored: dict | None, mined: dict | None) -> dict:
    out = dict(stored or {})
    for k, v in (mined or {}).items():
        if v not in (None, "", "unknown") and not out.get(k):
            out[k] = v
    return out


def _enrich_qualification_from_history(
    slot: str,
    user_id: int,
    qualification: dict,
    *,
    history_limit: int = 40,
) -> dict:
    """Load a deeper thread slice and persist newly mined facts."""
    full_history = _recent_conversation(slot, int(user_id), limit=history_limit)
    mined = _mine_conversation_facts(full_history)
    merged = _merge_qualification(qualification, mined)
    if mined and merged != qualification:
        update_lead_state(slot, int(user_id), qualification=merged)
        try:
            from core.lead_graph import sync_ai_to_crm

            state = get_lead_state(slot, int(user_id))
            sync_ai_to_crm(
                slot,
                int(user_id),
                stage=state.get("stage"),
                qualification=merged,
            )
        except Exception:
            logger.debug("lead_graph sync skipped after qualification enrich", exc_info=True)
    return merged


def _user_complains_repeat(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in _REPEAT_COMPLAINT_MARKERS)


def _user_availability_ping(user_text: str, history: list[dict] | None = None) -> bool:
    t = (user_text or "").lower().strip()
    if t in {"there?", "there", "hlo", "hlo?", "hello?", "hi?"}:
        return True
    if any(m in t for m in (
        "unnava", "unnara", "unnavaa", "are you there", "you there", "still there",
        "reply me", "respond", "anyone there", "hello karthik", "hi karthik",
        "there?", "hlo there", "wait, plz", "wait plz",
    )):
        return True
    if "karthik" in t and len(t.split()) <= 5:
        return True
    return False


def _recent_human_operator_hint(slot: str, user_id: int) -> str | None:
    """Name of operator who most recently introduced themselves (Vani, Kalyan, …)."""
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    for m in reversed(conv.get("messages") or []):
        if m.get("direction") != "out" or m.get("ai"):
            continue
        t = (m.get("text") or "").lower()
        if _staff.name("data_lead").lower() in t and any(x in t for x in ("this is", "i am", "iam", "my number", "call me")):
            return _staff.name("data_lead")
        if _staff.name("devops_lead").lower() in t and "this is" in t:
            return _staff.name("devops_lead")
        if "pavan" in t and any(x in t for x in ("this is", "i am", "fyn")):
            return "Pavan"
    return None


def _user_asks_which_operator(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(m in t for m in (
        "vani right", "is it vani", "vani?", "kalyan right", "right person",
        "who am i talking", "which person",
    ))


def _user_wants_demo(user_text: str, history: list[dict] | None = None) -> bool:
    t = (user_text or "").lower().strip()
    if any(m in t for m in (
        "demo kavali", "need demo", "want demo", "show demo", "give demo",
        "demo ivvu", "demo istha", "demo cheppu", "demo explain",
        "ela support", "how you support", "how do you support", "how support",
        "support ela", "support chestharo", "support chestaro",
    )):
        return True
    if _user_availability_ping(user_text, history):
        return False
    return False


def _demo_request_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
) -> str:
    known = _known_facts_for_reply(history, qualification, user_text)
    if _interview_fully_qualified(known, history, user_text):
        return _interview_support_smart_reply(
            known,
            history=history,
            user_text=user_text,
            qualification=qualification,
            lang=lang,
            lead=lead,
        )
    addr = _addr_prefix(lead, lang)
    tech = (known.get("tech_stack") or "").strip()
    timing = (known.get("interview_timing") or "").strip()
    team = _interview_tech_team_label(history, user_text, qualification, tech=tech)
    ctx = f"{tech} {timing} — ".strip() + " " if tech else ""
    return f"Got it {addr}👍 {ctx}{team} will give you a demo first 👍"


def _availability_ping_reply(
    user_text: str,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lang: str = "english",
    lead: dict | None = None,
    slot: str = "",
    user_id: int = 0,
) -> str:
    addr = _addr_prefix(lead, lang)
    if slot and user_id and _user_asks_which_operator(user_text):
        op = _recent_human_operator_hint(slot, int(user_id))
        if op == _staff.name("data_lead"):
            return f"Yes {addr}👍 {_staff.name('data_lead')} from our team — use {_staff.phone_digits('data_lead')} on WhatsApp 👍"
        if op == _staff.name("devops_lead"):
            return f"Yes {addr}👍 {_staff.name('devops_lead')} from our team — WhatsApp {_staff.phone_digits('devops_lead')} 👍"
    if slot and user_id and _recent_human_operator_hint(slot, int(user_id)):
        op = _recent_human_operator_hint(slot, int(user_id))
        if op and lang == "english":
            return f"Yes {addr}👍 {op} from our team will follow up — ping on the number they shared 👍"
    known = _known_facts_for_reply(history, qualification, user_text)
    tech = (known.get("tech_stack") or "").strip()
    timing = (known.get("interview_timing") or "").strip()
    recent_user = [
        (m.get("content") or "")
        for m in (history or [])
        if (m.get("role") or "").lower() in ("user", "human", "client")
    ][-3:]
    pending_demo = any(_user_wants_demo(msg) for msg in recent_user if msg != (user_text or ""))
    demo_bit = f" — {_tech_team_demo_phrase_short(lang)}" if pending_demo else ""
    if tech and timing:
        if lang == "english":
            return f"Yes {addr}👍 I'm here{demo_bit} for your {tech} interview 👍"
        return f"Yes {addr}👍 unnanu{demo_bit} — {tech} interview 👍"
    if lang == "english":
        return f"Yes {addr}👍 I'm here{demo_bit} 👍"
    return f"Yes {addr}👍 unnanu{demo_bit} 👍"


def _reply_from_known_facts(
    facts: dict,
    *,
    apologetic: bool = False,
    lang: str = "telugu",
    history: list[dict] | None = None,
    user_text: str = "",
) -> str:
    """Advance the conversation using facts we already have — never re-qualify."""
    prefix = "Sorry bro my bad 👍 " if apologetic else "Got it 👍 "
    tech = (facts.get("tech_stack") or "").strip()
    round_t = (facts.get("round_type") or "").strip()
    timing = (facts.get("interview_timing") or facts.get("deferral") or "").strip()
    service = (facts.get("service_need") or "").strip()

    if _user_offers_support_to_candidates(user_text, history) or _user_offers_support_to_candidates("", history):
        return _support_provider_inbound_reply(
            user_text, history=history, qualification=facts, lang=lang, lead=None,
        )

    t = (user_text or "").lower()
    if any(m in t for m in ("recording", "listen to", "voice sample", "sample call", "hear them", "listed their")):
        if _interview_support_service_needs(service, user_text, history) or resolve_thread_intent(
            history, user_text, facts,
        ) in (INTENT_INTERVIEW, INTENT_INTERVIEW_TILL_OFFER, INTENT_PROXY):
            return _interview_support_smart_reply(
                facts,
                history=history,
                user_text=user_text,
                qualification=facts,
                lang=lang,
                prefix=prefix,
            )

    if service == "resume building" or _user_wants_resume_documents(user_text, history):
        return _resume_document_reply(user_text, history=history, lang=lang)

    if (
        not _interview_support_service_needs(service, user_text, history)
        and (
            service in _JOB_SEARCH_SERVICES
            or _user_wants_job_search_support(user_text, history)
        )
    ):
        return _job_search_service_reply(
            history, user_text, lang=lang, prefix=prefix,
            include_price=_should_quote_price(user_text, history),
        )

    if facts.get("deferral") == "Tuesday" or timing == "Tuesday":
        if tech:
            if lang == "english":
                return f"{prefix}{tech} interview support noted — ping me Tuesday 👍"
            return f"{prefix}{tech} interview support noted — Tuesday ki ping cheyyandi 👍"
        if lang == "english":
            return f"{prefix}ping me Tuesday, we'll continue then 👍"
        return f"{prefix}Tuesday ki ping cheyyandi, appudu continue cheddam 👍"

    if tech and round_t and timing:
        if _interview_support_service_needs(service, user_text, history):
            return _interview_support_smart_reply(
                facts,
                history=history,
                user_text=user_text,
                qualification=facts,
                lang=lang,
                prefix=prefix,
            )
        if _is_data_analyst_domain(history, user_text, facts):
            return _vani_handoff_reply(reason="close_deal")
        if lang == "english":
            return (
                f"{prefix}{tech} {round_t} round {timing} noted — "
                f"slot confirms after payment 👍"
            )
        return (
            f"{prefix}{tech} {round_t} round {timing} noted — "
            f"payment ayyaka slot confirm chestham 👍"
        )

    if tech and round_t:
        if lang == "english":
            return f"{prefix}{tech} {round_t} round — when is the interview? 👍"
        return f"{prefix}{tech} {round_t} round — interview epudu undi? 👍"

    if tech and not _has_interview_timing_known(facts, history, user_text):
        if _user_wants_resume_documents(user_text, history):
            return _resume_document_reply(user_text, history=history, lang=lang)
        if _user_interview_not_scheduled(user_text, history):
            if lang == "english":
                return f"{prefix}{tech} noted — no interview date yet 👍 share when it's scheduled, or tell me if you need resume/doc help now"
            return f"{prefix}{tech} noted — interview date ledu inka 👍 schedule ayyaka cheppandi, leda resume/doc help kavala?"
        if (
            service in ("interview support", "interview support till offer letter", "proxy interview support")
            or _user_wants_interview_support(user_text, history)
        ):
            return _interview_timing_question(tech, lang=lang, prefix=prefix)

    if tech and not round_t:
        if _user_offers_support_to_candidates(user_text, history) or _user_offers_support_to_candidates("", history):
            return _support_provider_inbound_reply(
                user_text, history=history, qualification=facts, lang=lang, lead=None,
            )
        if _user_affirms_process_or_pricing(user_text, history):
            return _process_and_pricing_reply(facts, lang=lang, lead=None)
        if lang == "english":
            return f"{prefix}{tech} noted — client round or technical? 👍"
        return f"{prefix}{tech} noted — client round aa technical aa? 👍"

    if service == "interview support" and not tech:
        if lang == "english":
            return f"{prefix}interview support — which tech stack? 👍"
        return f"{prefix}interview support — mee tech stack cheppandi 👍"

    if apologetic:
        if lang == "english":
            return f"{prefix}let's continue from where we left 👍"
        return f"{prefix}continue cheddam from where we left 👍"
    return ""


def _fix_repeat_questions(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lang: str = "telugu",
) -> str:
    """Block re-asking tech/need when the thread already established them."""
    known = _merge_qualification(qualification, _mine_conversation_facts(history or [], user_text))

    if _user_complains_repeat(user_text):
        contextual = _reply_from_known_facts(
            known, apologetic=True, lang=lang, history=history, user_text=user_text,
        )
        if contextual:
            return contextual

    lower = (reply_text or "").lower()

    if _user_affirms_process_or_pricing(user_text, history):
        return _process_and_pricing_reply(known, lang=lang, lead=lead)

    if known.get("tech_stack") and any(p in lower for p in _ASK_TECH_MARKERS):
        contextual = _reply_from_known_facts(
            known, lang=lang, history=history, user_text=user_text,
        )
        if contextual:
            return contextual

    if known.get("tech_stack") and "client round or technical" in lower:
        if _user_affirms_process_or_pricing(user_text, history) or (
            (user_text or "").strip().lower() in ("yes", "both", "ok", "okay")
            and _assistant_offered_process_or_pricing(history)
        ):
            return _process_and_pricing_reply(known, lang=lang, lead=None)

    if known.get("service_need") and any(p in lower for p in _ASK_NEED_MARKERS):
        contextual = _reply_from_known_facts(
            known, lang=lang, history=history, user_text=user_text,
        )
        if contextual:
            return contextual

    if _looks_generic_assistant(reply_text) and len(history or []) >= 4:
        contextual = _reply_from_known_facts(
            known, lang=lang, history=history, user_text=user_text,
        )
        if contextual:
            return contextual

    return reply_text


def _known_facts_for_reply(
    history: list[dict] | None,
    qualification: dict | None,
    user_text: str = "",
) -> dict:
    facts = _merge_qualification(
        qualification, _mine_conversation_facts(history or [], user_text),
    )
    intent = resolve_thread_intent(history, user_text, facts)
    facts["thread_intent"] = intent
    if intent_blocks_dev_collab(intent):
        facts.pop("thread_type", None)
        if service_need_for_intent(intent):
            facts["service_need"] = service_need_for_intent(intent)
    elif intent == INTENT_DEV_COLLAB:
        for key in ("tech_stack", "domain", "round_type", "service_need"):
            facts.pop(key, None)
        facts["thread_type"] = "dev_collaboration_inbound"
    return facts


def _user_paid_or_ready_to_pay(user_text: str, history: list[dict] | None) -> bool:
    if _user_ready_for_payment(user_text):
        return True
    blob = _conversation_blob(history or [], user_text)
    return any(
        w in blob for w in (
            "paid", "payment done", "sent payment", "paid bro", "gpay chesa",
            "payment chesa", "amount sent", "transferred",
        )
    )


def _is_data_analyst_domain(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None = None,
) -> bool:
    blob = _conversation_blob(history or [], user_text)
    if any(m in blob for m in _DATA_ANALYST_MARKERS):
        return True
    qual = qualification or {}
    if qual.get("domain") == "data_analyst":
        return True
    stack = (qual.get("tech_stack") or "").lower()
    return any(m in stack for m in ("power bi", "tableau", "sql", "data analyst", "bi "))


def _is_ai_ml_domain(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None = None,
) -> bool:
    blob = _conversation_blob(history or [], user_text)
    if any(m in blob for m in _AI_ML_MARKERS):
        return True
    qual = qualification or {}
    if qual.get("domain") == "ai_ml":
        return True
    stack = (qual.get("tech_stack") or "").lower()
    return any(m in stack for m in ("ai", "ml", "machine learning", "llm", "genai"))


def _is_java_domain(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None = None,
) -> bool:
    blob = _conversation_blob(history or [], user_text)
    if _blob_has_java(blob):
        return True
    qual = qualification or {}
    if qual.get("domain") == "java":
        return True
    stack = (qual.get("tech_stack") or "").lower()
    if "java" in stack and "javascript" not in stack:
        return True
    return any(m in stack for m in ("spring", "hibernate", "j2ee"))


def _is_devops_domain(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None = None,
) -> bool:
    blob = _conversation_blob(history or [], user_text)
    if _is_ai_ml_domain(history, user_text, qualification):
        return False
    if any(m in blob for m in (
        "java production support", "java support developer", "java application support",
    )):
        return False
    if any(m in blob for m in _DEVOPS_MARKERS) or "devops" in blob:
        return True
    qual = qualification or {}
    if qual.get("domain") == "devops":
        return True
    stack = (qual.get("tech_stack") or "").lower()
    return any(m in stack for m in ("devops", "kubernetes", "docker", "terraform", "jenkins", "sre"))


def _is_react_frontend_domain(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None = None,
) -> bool:
    blob = _conversation_blob(history or [], user_text)
    if _is_java_domain(history, user_text, qualification):
        return False
    if any(m in blob for m in _REACT_FRONTEND_MARKERS):
        return True
    if any(t in blob for t in ("full stack", "fullstack", "full-stack")):
        if any(t in blob for t in ("react", "mern", "next.js", "nextjs", "frontend", "node.js", "nodejs")):
            return True
    qual = qualification or {}
    if qual.get("domain") == "react_frontend":
        return True
    stack = (qual.get("tech_stack") or "").lower()
    return any(m in stack for m in ("react", "mern", "next", "frontend", "javascript", "angular"))


def _looks_premature_slot_booking(reply_text: str) -> bool:
    lower = (reply_text or "").lower()
    return any(m in lower for m in _PREMATURE_SLOT_MARKERS)


def _vani_handoff_reply(*, empathy: bool = False, reason: str = "process") -> str:
    prefix = "Got it bro 👍 " if empathy else ""
    if reason == "process":
        lead = (
            "Power BI / data analyst side — Vani garu (senior data analyst) "
            "meeku process & support step-by-step explain chestharu"
        )
    elif reason == "free_confusion":
        lead = (
            "Sorry for confusion bro 👍 payment ayyaka ne slot confirm avutundi. "
            "Data analyst roles ki Vani garu (senior) clear ga explain chestharu"
        )
    elif reason == "close_deal":
        lead = (
            "Deal close / pricing / payment details ki Vani garu (senior data analyst) "
            "meeku help chestharu"
        )
    else:
        lead = "Data/BI/analytics details ki Vani garu (senior data analyst) help chestharu"
    return f"{prefix}{lead} 👍 📞 {VANI_PHONE} 📲 {VANI_WHATSAPP}"


def _satya_handoff_reply(*, empathy: bool = False, reason: str = "process") -> str:
    return _vani_handoff_reply(empathy=empathy, reason=reason)


def _react_handoff_reply(*, empathy: bool = False, reason: str = "process") -> str:
    prefix = "Got it bro 👍 " if empathy else ""
    if reason == "process":
        lead = (
            "React/Frontend side — Nikhila garu / Bhavana garu (seniors in React roles) "
            "meeku process & support step-by-step explain chestharu"
        )
    elif reason == "free_confusion":
        lead = (
            "Sorry for confusion bro 👍 payment ayyaka ne slot confirm avutundi. "
            "React/Frontend roles ki Nikhila / Bhavana garu (seniors) clear ga explain chestharu"
        )
    elif reason == "close_deal":
        lead = (
            "Deal close / detailed convincing ki Nikhila / Bhavana garu "
            "(seniors — React & Frontend) meeku help chestharu"
        )
    else:
        lead = "React/Frontend details ki Nikhila / Bhavana garu (seniors) help chestharu"
    return (
        f"{prefix}{lead} 👍 "
        f"Nikhila 📞 {NIKHILA_PHONE} 📲 {NIKHILA_WHATSAPP} | "
        f"Bhavana 📞 {BHAVANA_PHONE} 📲 {BHAVANA_WHATSAPP}"
    )


def _kalyan_handoff_reply(*, empathy: bool = False, reason: str = "process") -> str:
    prefix = "Got it bro 👍 " if empathy else ""
    senior = "Kalyan garu (most senior in DevOps & Cloud roles)"
    if reason == "process":
        lead = f"DevOps/Cloud/Infrastructure side — {senior} meeku process & support step-by-step explain chestharu"
    elif reason == "free_confusion":
        lead = (
            f"Sorry for confusion bro 👍 payment ayyaka ne slot confirm avutundi. "
            f"DevOps roles ki {senior} clear ga explain chestharu"
        )
    elif reason == "close_deal":
        lead = f"Deal close / detailed convincing ki {senior} meeku help chestharu"
    else:
        lead = f"DevOps/Cloud details ki {senior} help chestharu"
    return f"{prefix}{lead} 👍 📞 {KALYAN_PHONE} 📲 {KALYAN_WHATSAPP}"


def _senior_contact_line(
    history: list[dict] | None,
    user_text: str,
    qualification: dict | None,
) -> str:
    if _is_data_analyst_domain(history, user_text, qualification):
        return f"Vani garu (senior data analyst) help chestharu 📞 {VANI_PHONE} 📲 {VANI_WHATSAPP}"
    if _is_devops_domain(history, user_text, qualification):
        return f"Kalyan garu help chestharu 📞 {KALYAN_PHONE} 📲 {KALYAN_WHATSAPP}"
    if _is_react_frontend_domain(history, user_text, qualification):
        return (
            f"Nikhila / Bhavana garu help chestharu "
            f"Nikhila 📞 {NIKHILA_PHONE} 📲 {NIKHILA_WHATSAPP} | "
            f"Bhavana 📞 {BHAVANA_PHONE} 📲 {BHAVANA_WHATSAPP}"
        )
    return f"Thirlok garu help chestharu 📞 {THRILOK_PHONE} 📲 {THRILOK_WHATSAPP}"


def _senior_handoff_reply(
    *,
    empathy: bool = False,
    reason: str = "process",
    history: list[dict] | None = None,
    user_text: str = "",
    qualification: dict | None = None,
) -> str:
    """Data/Power BI → Vani. DevOps → Kalyan. React → Nikhila/Bhavana. Java/AI/other → Thirlok."""
    if _is_data_analyst_domain(history, user_text, qualification):
        return _vani_handoff_reply(empathy=empathy, reason=reason)
    if _is_devops_domain(history, user_text, qualification):
        return _kalyan_handoff_reply(empathy=empathy, reason=reason)
    if _is_react_frontend_domain(history, user_text, qualification):
        return _react_handoff_reply(empathy=empathy, reason=reason)
    return _thrilok_handoff_reply(empathy=empathy, reason=reason)


def _thrilok_handoff_reply(*, empathy: bool = False, reason: str = "process") -> str:
    prefix = "Got it bro 👍 " if empathy else ""
    if reason == "process":
        lead = (
            "Interview lo ela support chestamo — Thirlok garu (senior software engineer) "
            "meeku step-by-step explain chestharu"
        )
    elif reason == "free_confusion":
        lead = (
            "Sorry for confusion bro 👍 payment ayyaka ne slot confirm avutundi. "
            "Process clear ga cheppadaniki Thirlok garu (senior software engineer) help chestharu"
        )
    else:
        lead = "Process details ki Thirlok garu (senior software engineer) help chestharu"
    return f"{prefix}{lead} 👍 📞 {THRILOK_PHONE} 📲 {THRILOK_WHATSAPP}"


def _urgency_no_booking_reply(
    history: list[dict] | None,
    qualification: dict | None,
    *,
    user_text: str = "",
    lang: str | None = None,
) -> str:
    lang = lang or _detect_client_language(history, user_text)
    known = _known_facts_for_reply(history, qualification, user_text)
    tech = (known.get("tech_stack") or "").strip()
    round_t = (known.get("round_type") or "technical").strip()
    if tech:
        senior_line = _senior_contact_line(history, user_text, qualification)
        return (
            f"Got it bro, I understand the urgency 👍 {tech} {round_t} round ki interview support untadi — "
            f"{_tech_team_demo_phrase_short(lang)}. "
            f"Slot confirm cheyyadaniki mundu payment avvali — ready unte cheppandi. "
            f"Lekapothey details ki {senior_line}"
        )
    return _senior_handoff_reply(empathy=True, reason="process", history=history, user_text=user_text, qualification=qualification)


def _enforce_demo_availability_rules(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
    lead: dict | None = None,
) -> str:
    """Ask client demo availability — never assume interview time or push payment early."""
    if not _looks_premature_demo_schedule(reply_text, user_text, history):
        return reply_text
    lang = _detect_client_language(history or [], user_text)
    return _demo_availability_reply(
        history=history,
        user_text=user_text,
        qualification=qualification,
        lang=lang,
        lead=lead,
    )


def _enforce_slot_payment_rules(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None,
) -> str:
    """Never book/confirm slot before payment; hand off doubters to Thrilok."""
    history = history or []

    if _user_paid_or_ready_to_pay(user_text, history):
        return reply_text

    t = (user_text or "").lower()
    if _user_asks_pay_after_interview(user_text, history):
        return _pay_after_interview_reply(
            user_text, history=history, qualification=qualification, lang=_detect_client_language(history, user_text), lead=None,
        )
    if any(m in t for m in _DOUBT_MARKERS):
        return _senior_handoff_reply(
            empathy=True, reason="close_deal", history=history,
            user_text=user_text, qualification=qualification,
        )

    if _looks_premature_slot_booking(reply_text):
        known = _known_facts_for_reply(history, qualification, user_text)
        lang = _detect_client_language(history, user_text)
        if _interview_fully_qualified(known, history, user_text):
            return _interview_support_smart_reply(
                known,
                history=history,
                user_text=user_text,
                qualification=qualification,
                lang=lang,
            )
        return _urgency_no_booking_reply(history, qualification, user_text=user_text, lang=lang)

    lower = (reply_text or "").lower()
    if ("confirm the slot" in lower or "ready to confirm" in lower) and not _user_ready_for_payment(user_text):
        return _senior_handoff_reply(
            empathy=True, reason="free_confusion", history=history,
            user_text=user_text, qualification=qualification,
        )

    if any(m in t for m in _URGENCY_EMPATHY_MARKERS) and _looks_premature_slot_booking(reply_text):
        lang = _detect_client_language(history, user_text)
        return _urgency_no_booking_reply(history, qualification, user_text=user_text, lang=lang)

    # LLM said "we'll support" + "block slot" style closure without payment path
    lower = (reply_text or "").lower()
    if any(m in t for m in _URGENCY_EMPATHY_MARKERS):
        if "block" in lower and "slot" in lower:
            lang = _detect_client_language(history, user_text)
            return _urgency_no_booking_reply(history, qualification, user_text=user_text, lang=lang)

    return reply_text


def _user_needs_thrilok_handoff(user_text: str, history: list[dict] | None = None) -> str | None:
    """Return handoff reason when Karthik must NOT dodge — escalate to Thirlok."""
    if _user_asks_pay_after_interview(user_text, history):
        return "pay_after"
    t = (user_text or "").lower()
    if any(m in t for m in _PROCESS_QUESTION_MARKERS):
        return "process"
    if any(m in t for m in _FREE_CONFUSION_MARKERS):
        return "free_confusion"
    if any(m in t for m in _DOUBT_MARKERS):
        return "doubt"
    return None


def _enforce_thrilok_handoff(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None = None,
) -> str:
    """Never skip hard questions — hand off to Vani (data/Power BI) or Thirlok (interview/dev)."""
    reason = _user_needs_thrilok_handoff(user_text, history)
    if reason == "pay_after":
        lang = _detect_client_language(history, user_text)
        return _pay_after_interview_reply(
            user_text, history=history, qualification=qualification, lang=lang,
        )
    if reason:
        return _senior_handoff_reply(
            empathy=True, reason=reason, history=history,
            user_text=user_text, qualification=qualification,
        )

    t = (user_text or "").lower()
    lower = (reply_text or "").lower()

    if any(m in lower for m in _DODGE_REPLY_MARKERS):
        if any(m in t for m in _PROCESS_QUESTION_MARKERS + _FREE_CONFUSION_MARKERS + _DOUBT_MARKERS):
            return _senior_handoff_reply(
                empathy=True, reason="process", history=history,
                user_text=user_text, qualification=qualification,
            )

    if "confirm the slot" in lower or "ready to confirm" in lower:
        if not _user_paid_or_ready_to_pay(user_text, history or []):
            if any(m in t for m in _FREE_CONFUSION_MARKERS + _PROCESS_QUESTION_MARKERS):
                return _senior_handoff_reply(
                    empathy=True, reason="free_confusion", history=history,
                    user_text=user_text, qualification=qualification,
                )

    return reply_text


def _enforce_karthik_data_analyst_rules(
    reply_text: str,
    user_text: str,
    *,
    history: list[dict] | None,
    qualification: dict | None = None,
) -> str:
    """Power BI / data-analyst: Karthik qualifies tech only; never quotes ₹; Vani closes."""
    if not _is_data_analyst_domain(history, user_text, qualification):
        return reply_text

    if _reply_has_pricing(reply_text):
        reason = "close_deal" if _user_asked_price_in_thread(history, user_text) else "process"
        return _vani_handoff_reply(empathy=_user_complains_repeat(user_text), reason=reason)

    handoff_reason = _user_needs_thrilok_handoff(user_text, history)
    if handoff_reason:
        return _vani_handoff_reply(empathy=True, reason=handoff_reason)

    lower = (reply_text or "").lower()
    if any(m in lower for m in _DODGE_REPLY_MARKERS):
        if any(
            m in (user_text or "").lower()
            for m in _PROCESS_QUESTION_MARKERS + _FREE_CONFUSION_MARKERS + _DOUBT_MARKERS
        ):
            return _vani_handoff_reply(empathy=True, reason="process")

    known = _known_facts_for_reply(history, qualification, user_text)
    tech = (known.get("tech_stack") or "").strip()
    if tech and (
        _user_asked_price_in_thread(history, user_text)
        or _user_ready_for_payment(user_text)
        or _interview_fully_qualified(known, history, user_text)
    ):
        if _staff.name("data_lead").lower() not in lower and _staff.phone_digits("data_lead") not in lower.replace(" ", ""):
            reason = "close_deal" if _user_asked_price_in_thread(history, user_text) else "process"
            return _vani_handoff_reply(reason=reason)

    return reply_text


def _thread_continuation(
    history: list[dict],
    qualification: dict | None,
    user_text: str,
    lang: str = "telugu",
) -> str:
    """Pick up the active topic — never reset to generic 'how can I help'."""
    qual = _known_facts_for_reply(history, qualification, user_text)
    blob = _conversation_blob(history, user_text)
    en = lang == "english"

    if _user_asks_backdoor_jobs(user_text, history) or _user_asks_backdoor_jobs("", history):
        return _backdoor_jobs_reply(user_text, history=history, lang=lang)

    if _user_asks_pay_after_interview(user_text, history):
        return _pay_after_interview_reply(
            user_text, history=history, qualification=qualification, lang=lang,
        )

    if _user_seeks_dev_collaboration(user_text, history) or _user_seeks_dev_collaboration("", history):
        return _dev_collaboration_reply(user_text, history=history, lang=lang)

    if _user_wants_interview_support(user_text, history) or _interview_support_service_needs(
        (qual.get("service_need") or "").strip(), user_text, history,
    ):
        tech = (qual.get("tech_stack") or "").strip()
        round_t = (qual.get("round_type") or "").strip()
        timing = (qual.get("interview_timing") or qual.get("deferral") or "").strip()
        if tech and round_t and _has_interview_timing_known(qual, history, user_text):
            return _interview_support_smart_reply(
                qual,
                history=history,
                user_text=user_text,
                qualification=qualification,
                lang=lang,
            )
        if tech:
            contextual = _reply_from_known_facts(
                qual, lang=lang, history=history, user_text=user_text,
            )
            if contextual:
                return contextual

    if _user_wants_job_search_support(user_text, history):
        return _job_search_service_reply(
            history, user_text, lang=lang,
            include_price=_should_quote_price(user_text, history),
        )

    if _user_wants_job_help(user_text, history):
        return _job_seeker_reply(user_text, history=history, lang=lang)

    if _user_reopened_after_bye(user_text, history):
        return _reopen_after_bye_reply(lang=lang)

    if _user_wants_resume_documents(user_text, history):
        return _resume_document_reply(user_text, history=history, lang=lang)

    if _user_is_vendor_partner("", history):
        ctx = _vendor_context_label(history, user_text)
        if en:
            return f"Let's continue the {ctx} conversation — partnership or live round support? 👍"
        return f"{ctx} side continue cheddam — partnership na round support na? 👍"

    if qual.get("deferral") == "Tuesday" or "tuesday" in blob:
        tech = (qual.get("tech_stack") or "").strip()
        if tech:
            return f"{tech} interview support — ping me Tuesday 👍" if en else f"{tech} interview support — Tuesday ki ping cheyyandi 👍"
        return "Ping me Tuesday, we'll continue interview chat 👍" if en else "Tuesday ki ping cheyyandi, interview side continue cheddam 👍"
    if _user_deferred(user_text) or any(
        m in blob for m in ("later", "call later", "will update", "let me check", "ping me")
    ):
        return "Sure bro, ping me when ready — we'll continue then 👍" if en else "sure bro, ready unte ping cheyyandi — appudu continue cheddam 👍"

    tech = (qual.get("tech_stack") or "").strip()
    if tech == "MEAN" and "mean stack" not in blob and not re.search(r"\bmean\b", blob):
        tech = ""
    if tech:
        round_t = (qual.get("round_type") or "").strip()
        if round_t:
            return f"{tech} {round_t} round — let's continue 👍" if en else f"{tech} {round_t} round side continue cheddam 👍"
        if not _has_interview_timing_known(qual, history, user_text) and _user_wants_interview_support(user_text, history):
            return _interview_timing_question(tech, lang=lang, prefix="Got it 👍 ")
        return f"{tech} interview support — let's continue 👍" if en else f"{tech} interview support side continue cheddam 👍"

    if _user_wants_job_help(user_text, history):
        return _job_seeker_reply(user_text, history=history, lang=lang)

    for kw in ("react", "java", "python", "angular", "node", "dotnet", ".net", "frontend", "backend"):
        if kw in blob:
            return "Let's continue interview support — slot confirms after payment 👍" if en else "interview support side continue cheddam — payment ayyaka slot confirm chestham 👍"

    if any(w in blob for w in ("interview", "round", "client round", "technical round", "slot")):
        if _user_asks_backdoor_jobs("", history) or _user_wants_job_help("", history):
            return _backdoor_jobs_reply(user_text, history=history, lang=lang)
        return "Let's continue interview prep — when is your round? 👍" if en else "interview prep side continue cheddam — epudu undi mee round? 👍"

    if any(w in blob for w in ("charge", "price", "how much", "entha", "rate", "5000", "cost")):
        return "Already shared price & process — ping me when ready 👍" if en else "price & process explain chesa kada — ready unte Tuesday ki ping cheyyandi 👍"

    if any(w in blob for w in ("qr", "payment", "upi", "pay")):
        return "Payment later — let's clarify the process first 👍" if en else "payment vishayam tarvata — mundu process clear ga discuss cheddam 👍"

    if _user_probes_identity(user_text) or any(m in blob for m in _AI_PROBE_MARKERS):
        return "Real person — let's focus on your interview 👍" if en else "real person — mee interview side focus cheddam 👍"

    return ""


def _humanize_reply(
    reply_text: str,
    user_text: str,
    cfg: dict,
    *,
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lead: dict | None = None,
    slot: str = "",
    user_id: int = 0,
) -> str:
    """Override robotic loops — contextual name/identity replies when mid-conversation."""
    assistant_name = (cfg.get("assistant_name") or "").strip() or "Karthik"
    history = history or []
    lang = _detect_client_language(history, user_text)
    lead = lead or {}
    if _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history):
        return _enforce_name_not_bro(
            _enforce_short_reply(
                _vendor_partner_reply(
                    user_text,
                    history=history,
                    qualification=qualification,
                    lang=lang,
                    lead=lead,
                )
            ),
            lead,
            lang,
        )
    if _job_support_thread_closed(user_text, history):
        return _enforce_name_not_bro(
            _enforce_short_reply(_job_support_closed_ack(lang, lead)),
            lead,
            lang,
        )
    if _user_requests_india_job_support(user_text, history):
        return _enforce_name_not_bro(
            _enforce_short_reply(_india_no_job_support_reply(lang=lang, lead=lead)),
            lead,
            lang,
        )
    known = _known_facts_for_reply(history, qualification, user_text)
    if _user_affirms_process_or_pricing(user_text, history):
        return _enforce_name_not_bro(
            _enforce_short_reply(
                _enforce_client_language(
                    _process_and_pricing_reply(known, lang=lang, lead=lead),
                    lang,
                )
            ),
            lead,
            lang,
        )

    if _user_inquiring_about_our_services(user_text, history):
        if _is_data_analyst_domain(history, user_text, qualification):
            return _enforce_name_not_bro(
                _enforce_short_reply(
                    _enforce_client_language(
                        _vani_handoff_reply(
                            empathy=False,
                            reason="close_deal"
                            if _user_asked_price_in_thread(history, user_text)
                            else "process",
                        ),
                        lang,
                    )
                ),
                lead,
                lang,
            )
        t = (user_text or "").strip().lower()
        if any(w in t for w in ("call", "15 min", "15mins", "later")):
            addr = _addr_prefix(lead, lang)
            if lang == "english":
                return _enforce_name_not_bro(
                    f"Got it {addr}👍 no problem — ping me when you're free 👍",
                    lead,
                    lang,
                )
            return _enforce_name_not_bro(
                f"Got it {addr}👍 parledu — free ayyaka ping cheyyandi 👍",
                lead,
                lang,
            )

    if _user_asks_backdoor_jobs(user_text, history) or _user_asks_backdoor_jobs("", history):
        return _enforce_name_not_bro(
            _enforce_short_reply(
                _enforce_client_language(
                    _backdoor_jobs_reply(user_text, history=history, lang=lang, lead=lead),
                    lang,
                )
            ),
            lead,
            lang,
        )

    lower_reply = (reply_text or "").lower()
    if "backdoor" in lower_reply and "don't" not in lower_reply and "do not" not in lower_reply:
        if "deal with backdoor" in lower_reply or "we provide backdoor" in lower_reply:
            reply_text = _backdoor_jobs_reply(user_text, history=history, lang=lang, lead=lead)

    def _fin(text: str) -> str:
        out = _enforce_client_language(text, lang)
        if _assistant_recently_said(history, out) or _is_loop_reply(out):
            if _user_asks_proctoring("", history):
                out = _enforce_client_language(
                    _proctoring_service_reply(user_text, history=history, lang=lang, lead=lead), lang,
                )
            elif _user_short_decline(user_text):
                addr = _addr_prefix(lead, lang)
                if lang == "english":
                    out = f"Got it {addr}👍 ping me anytime."
                else:
                    out = f"Got it {addr}👍 ping cheyyandi 👍"
            else:
                social = _social_context_reply(
                    user_text, history=history, lang=lang, lead=lead, assistant_name=assistant_name,
                )
                if social:
                    out = _enforce_client_language(social, lang)
                elif _user_asks_pay_after_interview(user_text, history):
                    out = _enforce_client_language(
                        _pay_after_interview_reply(
                            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
                        ),
                        lang,
                    )
                else:
                    out = _enforce_client_language(
                        _intent_continuation_reply(
                            user_text, history=history, qualification=qualification,
                            lang=lang, lead=lead,
                        ),
                        lang,
                    )
        return _enforce_name_not_bro(_enforce_short_reply(out), lead, lang)

    if _user_wants_demo(user_text, history):
        return _fin(_demo_request_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        ))

    if _user_asks_demo_when(user_text, history):
        return _fin(_demo_availability_reply(
            history=history,
            user_text=user_text,
            qualification=qualification,
            lang=lang,
            lead=lead,
        ))

    if _user_availability_ping(user_text, history):
        return _fin(_availability_ping_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        ))

    if _user_asks_pay_after_interview(user_text, history):
        return _fin(_pay_after_interview_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        ))

    if _user_complains_repeat(user_text):
        return _fin(_reply_from_known_facts(
            _known_facts_for_reply(history, qualification, user_text),
            apologetic=True,
            lang=lang,
            history=history,
            user_text=user_text,
        ))

    if _user_asks_proctoring(user_text, history) or (
        _user_asks_proctoring("", history)
        and (
            _user_short_decline(user_text)
            or _looks_generic_assistant(reply_text)
            or "interview support, resume" in (reply_text or "").lower()
        )
    ):
        return _fin(_proctoring_service_reply(
            user_text, history=history, lang=lang, lead=lead,
        ))

    if _user_wants_resume_documents(user_text, history):
        return _fin(_resume_document_reply(
            user_text, history=history, lang=lang, lead=lead,
        ))

    if _user_offers_support_to_candidates(user_text, history) or _user_offers_support_to_candidates("", history):
        return _fin(_support_provider_inbound_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        ))

    if _user_seeks_dev_collaboration(user_text, history) or _user_seeks_dev_collaboration("", history):
        return _fin(_dev_collaboration_reply(
            user_text, history=history, lang=lang, lead=lead,
        ))

    if _reply_claims_dev_services(reply_text):
        return _fin(_dev_collaboration_reply(
            user_text, history=history, lang=lang, lead=lead,
        ))

    if _user_asks_backdoor_jobs(user_text, history) or _user_asks_backdoor_jobs("", history):
        return _fin(_backdoor_jobs_reply(
            user_text, history=history, lang=lang, lead=lead,
        ))

    if (
        _user_wants_abroad_job_placement(user_text, history)
        or _user_wants_abroad_job_placement("", history)
        or _user_names_abroad_region_only(user_text, history)
    ):
        return _fin(_abroad_job_policy_reply(
            user_text, history=history, lang=lang, lead=lead,
        ))

    if _user_wants_job_help(user_text, history) or _user_wants_job_help("", history):
        return _fin(_job_seeker_reply(
            user_text, history=history, lang=lang, lead=lead,
        ))

    if _user_reopened_after_bye(user_text, history):
        return _fin(_reopen_after_bye_reply(lang=lang, lead=lead))

    if _user_low_signal(user_text):
        if _user_wants_resume_documents("", history):
            return _fin(_resume_document_reply("", history=history, lang=lang, lead=lead))
        if len(history) >= 2:
            hook = _thread_continuation(history, qualification, user_text, lang)
            if hook:
                return _fin(hook)
        return _fin("")

    if _user_interview_not_scheduled(user_text, history):
        if _user_wants_resume_documents("", history):
            return _fin(_resume_document_reply(user_text, history=history, lang=lang, lead=lead))
        addr = _addr_prefix(lead, lang)
        if lang == "english":
            return _fin(f"Got it {addr}👍 no worries — ping me when your interview is scheduled 👍")
        return _fin(f"Got it {addr}👍 parvaledu — interview schedule ayyaka cheppandi 👍")

    if _user_short_decline(user_text) and len(history) >= 2:
        addr = _addr_prefix(lead, lang)
        if lang == "english":
            return _fin(f"Got it {addr}👍 ping me anytime.")
        return _fin(f"Got it {addr}👍 ping cheyyandi 👍")

    if _user_wants_phone_call(user_text, history) or _user_refuses_chat(user_text):
        if _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history):
            return _fin(_vendor_call_reply(
                user_text, history=history, qualification=qualification, lang=lang, lead=lead,
            ))
        return _fin(_call_handoff_reply(
            user_text, history=history, qualification=qualification,
            lang=lang, lead=lead, empathy=_user_refuses_chat(user_text),
        ))

    if (
        _active_call_whatsapp_thread(history, user_text)
        or (_user_short_ack(user_text) and _active_call_whatsapp_thread(history, ""))
    ) and (
        _looks_generic_assistant(reply_text)
        or _is_loop_reply(reply_text)
        or any(m in (reply_text or "").lower() for m in _OFFLINE_AUTO_MARKERS)
    ):
        return _fin(_call_handoff_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        ))

    if _user_asks_offline_online(user_text, history) or (
        _reply_denies_offline(reply_text)
        and ("offline" in (user_text or "").lower() or "offline" in _conversation_blob(history or [], user_text, tail=12))
    ):
        return _fin(_offline_online_support_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        ))

    if _user_wants_proxy_call(user_text, history) or _reply_denies_proxy(reply_text):
        if _is_data_analyst_domain(history, user_text, qualification):
            return _fin(_data_analyst_proxy_reply(
                user_text,
                history=history,
                qualification=qualification,
                lang=lang,
                lead=lead,
            ))
        return _fin(_proxy_call_service_reply(
            user_text, history=history, qualification=qualification, lang=lang, lead=lead,
        ))

    vendor_thread = _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history)
    if vendor_thread and (
        _user_is_vendor_partner(user_text, history)
        or _user_small_talk(user_text)
        or _reply_looks_like_naukri_pitch(reply_text)
        or _looks_generic_assistant(reply_text)
    ):
        return _fin(_vendor_partner_reply(
            user_text,
            history=history,
            qualification=qualification,
            lang=lang,
            lead=lead,
            small_talk=_user_small_talk(user_text) and not _user_is_vendor_partner(user_text, history),
        ))

    social = _social_context_reply(
        user_text, history=history, lang=lang, lead=lead, assistant_name=assistant_name,
    )
    if social and (
        _user_confused(user_text)
        or _user_personal_question(user_text)
        or _user_small_talk(user_text)
        or _is_loop_reply(reply_text)
    ):
        return _fin(social)

    has_prior = len(history) >= 2
    hook = _thread_continuation(history, qualification, user_text, lang) if has_prior else ""

    if _user_asks_name(user_text):
        if _user_seeks_dev_collaboration("", history):
            addr = _addr_prefix(lead, lang)
            if lang == "english":
                return _fin(
                    f"I'm {assistant_name} {addr}👍 we do interview & job support for candidates — "
                    f"not dev freelancing on projects."
                )
            return _fin(
                f"I'm {assistant_name} {addr}👍 job seekers ki interview & job support — "
                f"project dev work cheyamu."
            )
        known = _known_facts_for_reply(history, qualification, user_text)
        if hook:
            return _fin(f"I'm {assistant_name} bro 👍 {hook}")
        tech = (known.get("tech_stack") or "").strip()
        if tech:
            if known.get("deferral") == "Tuesday":
                if lang == "english":
                    return _fin(f"I'm {assistant_name} bro 👍 {tech} interview support — ping me Tuesday 👍")
                return _fin(f"I'm {assistant_name} bro 👍 {tech} interview support — Tuesday ki ping cheyyandi 👍")
            round_t = (known.get("round_type") or "").strip()
            if round_t:
                if lang == "english":
                    return _fin(f"I'm {assistant_name} bro 👍 {tech} {round_t} round — let's continue 👍")
                return _fin(f"I'm {assistant_name} bro 👍 {tech} {round_t} round — continue cheddam 👍")
            if lang == "english":
                return _fin(f"I'm {assistant_name} bro 👍 let's continue {tech} interview support 👍")
            return _fin(f"I'm {assistant_name} bro 👍 {tech} interview support continue cheddam 👍")
        return _fin(f"I'm {assistant_name} bro 👍")

    if _user_probes_identity(user_text):
        if hook:
            return _fin(f"Haha no bro I'm {assistant_name} 😄 {hook}")
        return _fin(f"Haha no bro I'm {assistant_name} — real person from the team 😄")

    if _user_deferred(user_text):
        lower = (reply_text or "").lower()
        if any(p in lower for p in ("payment", " pay", "upi", "qr", "proceed", "ready to")):
            if "tuesday" in user_text.lower():
                return _fin(_okay_prefix(lead, lang) + "ping me Tuesday, no rush")
            return _fin(_okay_prefix(lead, lang) + "ping me when you're ready, no rush")

    if has_prior and (_looks_generic_assistant(reply_text) or _is_loop_reply(reply_text)):
        if _user_wants_demo(user_text, history):
            return _fin(_demo_request_reply(
                user_text, history=history, qualification=qualification, lang=lang, lead=lead,
            ))
        if _user_availability_ping(user_text, history):
            return _fin(_availability_ping_reply(
                user_text, history=history, qualification=qualification, lang=lang, lead=lead,
            ))
        if _user_asks_pay_after_interview(user_text, history):
            return _fin(_pay_after_interview_reply(
                user_text, history=history, qualification=qualification, lang=lang, lead=lead,
            ))
        if _user_complains_repeat(user_text):
            return _fin(_reply_from_known_facts(
                _known_facts_for_reply(history, qualification, user_text),
                apologetic=True, lang=lang, history=history, user_text=user_text,
            ))
        if _user_seeks_dev_collaboration("", history):
            return _fin(_dev_collaboration_reply(
                user_text, history=history, lang=lang, lead=lead,
            ))
        known = _known_facts_for_reply(history, qualification, user_text)
        if known.get("tech_stack") or known.get("service_need"):
            contextual = _reply_from_known_facts(
                known, lang=lang, history=history, user_text=user_text,
            )
            if contextual:
                return _fin(contextual)
        if hook:
            return _fin(hook)
        addr = _addr_prefix(lead, lang)
        if lang == "english":
            return _fin(f"Got it {addr}👍 let's continue from where we left 👍")
        return _fin(f"Got it {addr}👍 continue cheddam 👍")

    reply = _fix_repeat_questions(
        reply_text, user_text, history=history, qualification=qualification, lang=lang,
    )
    reply = _enforce_demo_availability_rules(
        reply, user_text, history=history, qualification=qualification, lead=lead,
    )
    reply = _enforce_slot_payment_rules(
        reply, user_text, history=history, qualification=qualification,
    )
    reply = _enforce_pricing_rules(reply, user_text, history=history)
    reply = _enforce_interview_support_service(
        reply, user_text, history=history, qualification=qualification, lang=lang, lead=lead,
    )
    reply = _enforce_thread_intent_coherence(
        reply, user_text, history=history, qualification=qualification, lang=lang, lead=lead,
    )
    reply = _enforce_abroad_job_policy(
        reply, user_text, history=history, lang=lang, lead=lead,
    )
    reply = _enforce_india_job_support_policy(
        reply, user_text, history=history, lang=lang, lead=lead,
    )
    reply = _enforce_job_search_service(reply, user_text, history=history, lang=lang)
    reply = _enforce_interview_exam_screenshot(
        reply,
        user_text,
        slot=slot,
        user_id=user_id,
        history=history,
        qualification=qualification,
        lang=lang,
        lead=lead,
    )
    reply = _enforce_interview_timing_first(
        reply, user_text, history=history, qualification=qualification, lang=lang,
    )
    reply = _enforce_value_before_price(
        reply, user_text, history=history, qualification=qualification, lang=lang,
    )
    reply = _enforce_call_handoff(
        reply, user_text, history=history, qualification=qualification, lang=lang, lead=lead,
    )
    reply = _enforce_proxy_service(
        reply, user_text, history=history, qualification=qualification, lang=lang, lead=lead,
    )
    reply = _enforce_whitelisted_contacts(
        reply, history=history, qualification=qualification, lang=lang,
    )
    reply = _enforce_no_repeat_qualify(
        reply, user_text, history=history, qualification=qualification, lang=lang, lead=lead,
    )
    reply = _enforce_reply_matches_facts(
        reply, user_text, history=history, qualification=qualification, lang=lang,
    )
    reply = _enforce_thrilok_handoff(
        reply, user_text, history=history, qualification=qualification,
    )
    reply = _enforce_karthik_data_analyst_rules(
        reply, user_text, history=history, qualification=qualification,
    )
    if _user_seeks_dev_collaboration(user_text, history) or (
        _reply_claims_dev_services(reply)
        and not intent_blocks_dev_collab(resolve_thread_intent(history, user_text, qualification))
    ):
        return _fin(_dev_collaboration_reply(
            user_text, history=history, lang=lang, lead=lead,
        ))
    return _fin(reply)


_GENERIC_ASSISTANT_MARKERS = (
    "what can i assist", "what do you need help", "how can i help", "what can i help",
    "what do you need assistance", "i'm just here to help", "assist you with today",
    "what do you need", "from the team! what", "what are you looking for help",
    "what help do you need", "what do you need help with", "i'm here! what",
    "interview support, resume help", "resume help, or naukri", "or naukri profile help",
    "something else?", "tell me more about what you need regarding",
    "if you have any specific questions", "just let me know if you need",
    "in the meantime, if you need", "feel free to ask",
)


def _looks_generic_assistant(reply_text: str) -> bool:
    lower = (reply_text or "").lower()
    return any(m in lower for m in _GENERIC_ASSISTANT_MARKERS)


async def generate_and_send(
    slot: str,
    user_id: int,
    *,
    user_message_id: int | None,
    user_text: str,
    force: bool = False,
) -> dict:
    """Background-executed: build context, call LLM, send the reply.

    Re-runs all gates from `maybe_schedule_ai_reply` because the queue delay
    may have made some of them stale (e.g. human stepped in while we waited).

    `force=True` (used by the manual "AI reply" button in the UI) bypasses the
    per-lead toggle, the `escalated` flag, the human-pause window, and the
    daily/hourly caps. The operator is explicitly asking for an AI reply right
    now, so the safety gates step out of the way. The global enable check and
    the spam/converted/not_interested status check still apply — those are
    intentional and never overridden.
    """
    if not is_enabled():
        return {"ok": False, "reason": "ai_disabled"}

    cfg = get_config()

    # Refresh lead snapshot (it may have changed since enqueue).
    from core.crm_store import get_lead

    lead = _enrich_lead_with_inbox_name(slot, int(user_id), get_lead(slot, int(user_id)) or {})
    if (lead.get("status") or "") in {"spam", "converted", "not_interested"}:
        return {"ok": False, "reason": "lead_inactive"}

    from core.spam_detector import is_telegram_service_chat

    if is_telegram_service_chat(
        user_text,
        name=(lead.get("name") or ""),
        username=(lead.get("username") or ""),
        user_id=int(user_id),
    ):
        return {"ok": False, "reason": "telegram_system"}

    from core.block_store import is_blocked

    if is_blocked(slot, int(user_id)):
        return {"ok": False, "reason": "blocked"}

    state = get_lead_state(slot, int(user_id))
    if force and state.get("escalated"):
        update_lead_state(slot, int(user_id), escalated=False)
        state = get_lead_state(slot, int(user_id))
    if not force and (not state.get("enabled", True) or state.get("escalated")):
        return {"ok": False, "reason": "ai_off_for_lead"}

    if not force:
        off_hours = await _maybe_send_off_hours_reply(
            slot, int(user_id), cfg=cfg, state=state, user_message_id=user_message_id,
        )
        if off_hours is not None:
            return off_hours

    if not force and user_message_id is not None:
        if not _inbound_still_unanswered(slot, int(user_id), int(user_message_id)):
            _monitor("ai_duplicate_prevented", slot=slot, user_id=user_id, reason="already_answered")
            return {"ok": False, "reason": "already_answered"}

    if not force:
        lock_reason = _human_only_lock_reason(slot, int(user_id), user_text)
        if lock_reason:
            disable_for_lead(slot, int(user_id), reason=lock_reason)
            return {"ok": False, "reason": lock_reason}

    # Honour human-pause again at execute time (unless explicitly forced).
    # AI replies also update last_reply_at, so disambiguate via the last
    # outbound's ai flag — only pause when the most recent outbound was human.
    if not force:
        last_reply_at = lead.get("last_reply_at")
        if last_reply_at and _is_last_outbound_human(slot, int(user_id)):
            try:
                last_reply_ts = datetime.fromisoformat(last_reply_at).timestamp()
                pause_min = float(cfg.get("human_pause_minutes", 10))
                if _lead_has_human_owned_thread(slot, int(user_id)):
                    pause_min = max(
                        pause_min,
                        float(os.getenv("AI_HUMAN_OWNED_PAUSE_MINUTES", "1440")),
                    )
                if time.time() - last_reply_ts < pause_min * 60:
                    return {"ok": False, "reason": "human_active"}
            except (TypeError, ValueError):
                pass

    # Build context — mine facts from deep history so we never re-ask known details.
    history_limit = _effective_history_limit(cfg)
    history = _recent_conversation(slot, int(user_id), limit=history_limit)
    if not force and _job_support_thread_closed(user_text, history):
        _monitor(
            "ai_skipped",
            slot=slot,
            user_id=int(user_id),
            reason="job_support_declined_closed",
        )
        return {"ok": False, "reason": "job_support_declined_closed"}
    qualification = _enrich_qualification_from_history(
        slot,
        int(user_id),
        dict(state.get("qualification") or {}),
        history_limit=max(history_limit, 50),
    )
    _capture_data_room_opportunity(
        slot,
        int(user_id),
        user_text=user_text,
        history=history,
        lead=lead,
        qualification=qualification,
    )
    stage = state.get("stage") or STAGE_GREETING

    _monitor(
        "ai_thinking",
        slot=slot,
        user_id=int(user_id),
        stage=stage,
        history_count=len(history),
    )
    # Call the model first (think), then simulate human typing before send.
    ai_out: dict | None = None
    try:
        ai_out = await _call_llm(
            cfg=cfg,
            history=history,
            user_text=user_text,
            lead=lead,
            stage=stage,
            qualification=qualification,
            slot=slot,
            user_id=int(user_id),
        )
    except Exception as e:
        if _is_llm_transient_error(e):
            fallback = _reply_fallback_for_llm_outage(
                user_text,
                cfg,
                history=history,
                qualification=qualification,
                lead=lead,
                rate_limited=_is_llm_rate_limited(e),
            )
            if fallback.strip():
                logger.warning(
                    "ai_smart_reply LLM outage %s %s — rule fallback: %r",
                    slot,
                    user_id,
                    e,
                )
                _monitor(
                    "ai_fallback",
                    slot=slot,
                    user_id=int(user_id),
                    reason="llm_rate_limit" if _is_llm_rate_limited(e) else "llm_transient",
                )
                min_conf = float(cfg.get("min_confidence", 0.45) or 0.45)
                ai_out = {
                    "reply": fallback,
                    "should_send": True,
                    "escalate": False,
                    "next_stage": stage,
                    "confidence": min_conf,
                    "extracted_facts": {},
                }
        if ai_out is None:
            logger.warning("ai_smart_reply LLM error %s %s: %r", slot, user_id, e)
            _monitor("ai_failed", slot=slot, user_id=int(user_id), reason="llm_error")
            return {"ok": False, "reason": "llm_error", "error": repr(e)}

    reply_text = (ai_out.get("reply") or "").strip()
    escalate = bool(ai_out.get("escalate"))
    should_send = ai_out.get("should_send", True)
    next_stage = ai_out.get("next_stage") or stage
    extracted = ai_out.get("extracted_facts") or {}

    if escalate and (
        _user_availability_ping(user_text, history)
        or _user_wants_demo(user_text, history)
        or _user_complains_repeat(user_text)
    ):
        if _user_wants_demo(user_text, history):
            reply_text = _demo_request_reply(
                user_text, history=history, qualification=qualification, lang=_detect_client_language(history, user_text), lead=lead,
            )
        elif _user_availability_ping(user_text, history):
            reply_text = _availability_ping_reply(
                user_text,
                history=history,
                qualification=qualification,
                lang=_detect_client_language(history, user_text),
                lead=lead,
                slot=slot,
                user_id=int(user_id),
            )
        else:
            reply_text = _reply_from_known_facts(
                _known_facts_for_reply(history, qualification, user_text),
                apologetic=True,
                lang=_detect_client_language(history, user_text),
                history=history,
                user_text=user_text,
            )
        escalate = False
        should_send = bool(reply_text.strip())

    if escalate:
        fallback = _deterministic_reply_fallback(
            user_text, cfg, history=history, qualification=qualification, lead=lead,
        )
        if fallback.strip():
            escalate = False
            reply_text = fallback
            should_send = True

    if escalate:
        update_lead_state(
            slot,
            int(user_id),
            escalated=True,
            last_user_message_id=user_message_id,
        )
        await _broadcast_escalation(slot, int(user_id), reason="model_escalate")
        confidence = _resolve_confidence(ai_out, cfg)
        _monitor("ai_escalated", slot=slot, user_id=user_id, confidence=confidence)
        return {"ok": False, "reason": "escalated", "confidence": confidence}

    if not should_send or not reply_text:
        _monitor("ai_skipped", slot=slot, user_id=int(user_id), reason="no_reply_chosen")
        return {"ok": False, "reason": "no_reply_chosen"}

    confidence = _resolve_confidence(ai_out, cfg)
    min_conf = float(cfg.get("min_confidence", 0.45) or 0.45)
    if confidence < min_conf:
        fallback = _deterministic_reply_fallback(
            user_text, cfg, history=history, qualification=qualification, lead=lead,
        )
        if fallback.strip():
            reply_text = fallback
            confidence = min_conf
        else:
            logger.info(
                "ai_smart_reply low confidence skip %s %s (%.2f)",
                slot, user_id, confidence,
            )
            _monitor("ai_skipped", slot=slot, user_id=user_id, reason="low_confidence", confidence=confidence)
            return {"ok": False, "reason": "low_confidence", "confidence": confidence}

    # Safety pass on the text itself.
    reply_text = _sanitize_reply(reply_text, cfg, history=history)
    lang_send = _detect_client_language(history, user_text)
    screenshot_first = _maybe_interview_exam_screenshot_reply(
        slot,
        int(user_id),
        user_text,
        history=history,
        qualification=qualification,
        lang=lang_send,
        lead=lead,
    )
    if screenshot_first:
        reply_text = screenshot_first
    else:
        reply_text = _humanize_reply(
            reply_text,
            user_text,
            cfg,
            history=history,
            qualification=qualification,
            lead=lead,
            slot=slot,
            user_id=int(user_id),
        )
    reply_text = _sanitize_reply(reply_text, cfg, history=history)
    if len(history) >= 2 and _looks_generic_assistant(reply_text):
        intent = resolve_thread_intent(history, user_text, qualification)
        if intent_blocks_generic_menu(intent, qualification):
            contextual = _intent_continuation_reply(
                user_text, history=history, qualification=qualification,
                lang=_detect_client_language(history, user_text), lead=lead,
            )
            if contextual.strip():
                reply_text = contextual
        else:
            fallback = _deterministic_reply_fallback(
                user_text, cfg, history=history, qualification=qualification, lead=lead,
            )
            if fallback.strip():
                reply_text = fallback
    if _user_deferred(user_text):
        next_stage = STAGE_VALUE
    elif _user_wants_name_in_reply(user_text):
        next_stage = STAGE_QUALIFY
    if not reply_text:
        return {"ok": False, "reason": "sanitized_empty"}

    if not force and _duplicate_outbound_blocked(slot, int(user_id), reply_text):
        logger.info(
            "ai_smart_reply skip send %s %s — similar outbound just sent",
            slot, user_id,
        )
        _monitor("ai_duplicate_prevented", slot=slot, user_id=user_id, reason="similar_outbound")
        return {"ok": False, "reason": "duplicate_outbound"}

    # Simulate human typing delay + indicator before sending.
    try:
        await _simulate_human_typing(slot, int(user_id), reply_text, cfg)
    except Exception as e:
        logger.debug("ai_smart_reply typing sim %s %s: %s", slot, user_id, e)

    if not force and user_message_id is not None:
        if not _inbound_still_unanswered(slot, int(user_id), int(user_message_id)):
            logger.info(
                "ai_smart_reply skip send %s %s — inbound already answered",
                slot, user_id,
            )
            _monitor("ai_duplicate_prevented", slot=slot, user_id=user_id, reason="already_answered_pre_send")
            return {"ok": False, "reason": "already_answered"}

    if not force and _duplicate_outbound_blocked(slot, int(user_id), reply_text):
        logger.info(
            "ai_smart_reply skip send %s %s — similar outbound just sent (post-typing)",
            slot, user_id,
        )
        _monitor("ai_duplicate_prevented", slot=slot, user_id=user_id, reason="similar_outbound_post_typing")
        return {"ok": False, "reason": "duplicate_outbound"}

    # Send through Telegram or WhatsApp based on thread channel.
    from services.whatsapp_dispatch import dispatch_lead_reply

    _monitor("ai_send_started", slot=slot, user_id=int(user_id), reply_len=len(reply_text))
    send_res = None
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            send_res = await dispatch_lead_reply(
                slot, int(user_id), reply_text, sent_by="ai",
            )
            break
        except Exception as e:
            last_err = e
            if "database is locked" not in str(e).lower() or attempt >= 5:
                logger.warning("ai_smart_reply send %s %s: %s", slot, user_id, e)
                _monitor("ai_failed", slot=slot, user_id=int(user_id), reason="send_failed")
                return {"ok": False, "reason": "send_failed", "error": str(e)}
            await asyncio.sleep(1.5 * (attempt + 1))
    if send_res is None:
        err = str(last_err) if last_err else "send_failed"
        return {"ok": False, "reason": "send_failed", "error": err}

    # Optionally attach payment QR when the model flags it (trust gate applies).
    send_qr = _payment_qr_allowed(
        user_text=user_text,
        history=history,
        stage=stage,
        next_stage=next_stage,
        ai_out=ai_out,
        slot=slot,
        user_id=int(user_id),
        state=state,
    )
    if bool(ai_out.get("send_payment_qr")) and not send_qr:
        logger.info(
            "ai_smart_reply payment QR suppressed %s %s (trust-first)",
            slot, user_id,
        )
    if send_qr:
        try:
            from core.whatsapp_channel import pick_reply_channel

            if pick_reply_channel(slot, int(user_id)) != "whatsapp":
                await _send_payment_qr(slot, int(user_id), cfg)
                update_lead_state(
                    slot,
                    int(user_id),
                    payment_qr_sent_count=int(state.get("payment_qr_sent_count") or 0) + 1,
                )
        except Exception as e:
            logger.warning("ai_smart_reply payment QR %s %s: %s", slot, user_id, e)

    # After demo timing is confirmed, send install links (UltraViewer + LockedIn AI).
    try:
        from features.demo_tools import maybe_auto_send_demo_tools

        merged_qual = _merge_qualification(
            qualification,
            extracted if isinstance(extracted, dict) else None,
        )
        await maybe_auto_send_demo_tools(
            slot,
            int(user_id),
            user_text=user_text,
            history=history,
            qualification=merged_qual,
            lead=lead,
        )
    except Exception as e:
        logger.debug("demo_tools auto-send %s %s: %s", slot, user_id, e)

    # Tag the persisted record as ai-generated so the UI can render a badge.
    try:
        record = send_res.get("message") or {}
        mid = record.get("id")
        if mid:
            _tag_message_as_ai(slot, int(user_id), int(mid), stage=next_stage, confidence=confidence)
    except Exception:
        pass

    # Persist new stage + extracted facts + counters.
    record_account_reply(slot)
    intent_facts = _known_facts_for_reply(history, qualification, user_text)
    if isinstance(extracted, dict):
        extracted = {**extracted, **{k: intent_facts[k] for k in ("thread_intent", "service_need") if intent_facts.get(k)}}
        if intent_blocks_dev_collab(intent_facts.get("thread_intent", "")):
            extracted.pop("thread_type", None)
    else:
        extracted = {k: intent_facts[k] for k in ("thread_intent", "service_need") if intent_facts.get(k)} or None
    record_ai_reply(
        slot,
        int(user_id),
        stage=next_stage if next_stage in VALID_STAGES else stage,
        qualification_patch=extracted if isinstance(extracted, dict) else None,
    )
    update_lead_state(slot, int(user_id), last_user_message_id=user_message_id)

    try:
        from core.lead_graph import sync_ai_to_crm

        merged_qual = _merge_qualification(
            qualification,
            extracted if isinstance(extracted, dict) else None,
        )
        sync_ai_to_crm(
            slot,
            int(user_id),
            stage=next_stage if next_stage in VALID_STAGES else stage,
            qualification=merged_qual,
        )
    except Exception:
        logger.debug("lead_graph sync skipped after ai send", exc_info=True)

    _monitor(
        "ai_sent",
        slot=slot,
        user_id=int(user_id),
        stage=str(next_stage),
        confidence=confidence,
        reply_len=len(reply_text),
    )
    return {
        "ok": True,
        "stage": next_stage,
        "confidence": confidence,
        "reply": reply_text,
    }


async def generate_suggestion(
    slot: str,
    user_id: int,
    *,
    user_message_id: int | None,
    user_text: str,
) -> dict:
    """Generate a draft reply WITHOUT sending it.

    This is the workhorse for the "Suggest reply" button in the inbox UI.
    It runs the same context-building + LLM call as `generate_and_send`,
    but stops before any Telegram I/O. The caller receives the draft text
    and decides whether to forward it to the regular send pipeline.

    Returns:
        {
          "ok": True,
          "text": "<draft>",        # never None when ok=True
          "stage": "<stage>",       # what the AI thinks comes next
          "confidence": float,      # 0-1
          "ai": True,
        }
    or an error shape: {"ok": False, "reason": "...", "error": "..."}.

    All safety gates (LLM error, low confidence → escalate, empty
    sanitised text) still apply; the only thing we skip is the actual
    `dm_inbox_service.run_dm_send` call and the throttle/state updates
    that were tied to sending. We still call `update_lead_state` with
    `last_user_message_id` so the operator can't accidentally generate
    a fresh draft for the same message twice in a row.
    """
    if not is_enabled():
        return {"ok": False, "reason": "ai_disabled"}

    # Knowledge-assessment gate. Karthik can't draft for real clients
    # until he passes the knowledge battery (or the operator manually
    # overrides). See core/ai_assessment.py for the full rubric.
    from core.ai_smart_reply_store import is_assessment_approved
    if not is_assessment_approved():
        return {
            "ok":     False,
            "reason": "assessment_required",
            "error":  "Run the Karthik knowledge assessment in AI Settings before generating suggestions.",
        }

    cfg = get_config()
    from core.crm_store import get_lead
    lead = _enrich_lead_with_inbox_name(slot, int(user_id), get_lead(slot, int(user_id)) or {})
    state = get_lead_state(slot, int(user_id))
    qualification = dict(state.get("qualification") or {})
    stage = state.get("stage") or STAGE_GREETING
    history_limit = _effective_history_limit(cfg)
    history = _recent_conversation(slot, int(user_id), limit=history_limit)
    qualification = _enrich_qualification_from_history(
        slot, int(user_id), qualification, history_limit=max(history_limit, 50),
    )

    ai_out: dict | None = None
    try:
        ai_out = await _call_llm(
            cfg=cfg,
            history=history,
            user_text=user_text,
            lead=lead,
            stage=stage,
            qualification=qualification,
            slot=slot,
            user_id=int(user_id),
        )
    except Exception as e:
        if _is_llm_transient_error(e):
            fallback = _reply_fallback_for_llm_outage(
                user_text,
                cfg,
                history=history,
                qualification=qualification,
                lead=lead,
                rate_limited=_is_llm_rate_limited(e),
            )
            if fallback.strip():
                logger.warning(
                    "ai_smart_reply draft LLM outage %s %s — rule fallback: %r",
                    slot,
                    user_id,
                    e,
                )
                min_conf = float(cfg.get("min_confidence", 0.45) or 0.45)
                ai_out = {
                    "reply": fallback,
                    "should_send": True,
                    "escalate": False,
                    "next_stage": stage,
                    "confidence": min_conf,
                    "extracted_facts": {},
                }
        if ai_out is None:
            logger.warning("ai_smart_reply LLM error %s %s: %s", slot, user_id, e)
            return {"ok": False, "reason": "llm_error", "error": str(e)}

    reply_text = (ai_out.get("reply") or "").strip()
    next_stage = ai_out.get("next_stage") or stage
    escalate = bool(ai_out.get("escalate"))
    confidence = _resolve_confidence(ai_out, cfg)

    reply_text = _sanitize_reply(reply_text, cfg, history=history)
    reply_text = _humanize_reply(
        reply_text, user_text, cfg, history=history, qualification=qualification, lead=lead,
    )
    reply_text = _sanitize_reply(reply_text, cfg, history=history)
    if not reply_text:
        outage_fb = _reply_fallback_for_llm_outage(
            user_text, cfg, history=history, qualification=qualification, lead=lead,
        )
        if outage_fb.strip():
            reply_text = _sanitize_reply(
                _humanize_reply(
                    outage_fb, user_text, cfg,
                    history=history, qualification=qualification, lead=lead,
                ),
                cfg,
                history=history,
            )
    if not reply_text:
        return {"ok": False, "reason": "empty_draft", "confidence": confidence}

    extracted = ai_out.get("extracted_facts") or {}
    try:
        merged_qual = _merge_qualification(
            qualification,
            extracted if isinstance(extracted, dict) else None,
        )
        if extracted:
            update_lead_state(slot, int(user_id), qualification=merged_qual)
        from core.lead_graph import sync_ai_to_crm

        sync_ai_to_crm(
            slot,
            int(user_id),
            stage=next_stage,
            qualification=merged_qual,
        )
    except Exception:
        logger.debug("lead_graph sync skipped after suggestion", exc_info=True)

    return {
        "ok": True,
        "text": reply_text,
        "stage": next_stage,
        "confidence": confidence,
        "escalate": escalate,
        "ai": True,
    }


def disable_for_lead(slot: str, user_id: int, *, reason: str = "manual") -> dict:
    return update_lead_state(slot, int(user_id), enabled=False, escalated=True, _disable_reason=reason)


def enable_for_lead(slot: str, user_id: int) -> dict:
    return update_lead_state(
        slot,
        int(user_id),
        enabled=True,
        escalated=False,
        last_user_message_id=None,
        _disable_reason=None,
    )


def _inbound_still_unanswered(slot: str, user_id: int, message_id: int) -> bool:
    """True when the given inbound message is still the latest with no outbound after it."""
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    msgs = conv.get("messages") or []
    if not msgs:
        return False
    last = msgs[-1]
    if last.get("direction") != "in":
        return False
    try:
        return int(last.get("id") or 0) == int(message_id)
    except (TypeError, ValueError):
        return False


# ── Full-thread context for LLM ─────────────────────────────────────────────

MIN_LLM_HISTORY_MESSAGES = 40
MAX_LLM_HISTORY_MESSAGES = 60


def _effective_history_limit(cfg: dict) -> int:
    """Always send enough messages so Karthik sees the full active thread."""
    try:
        raw = int(cfg.get("history_messages") or MIN_LLM_HISTORY_MESSAGES)
    except (TypeError, ValueError):
        raw = MIN_LLM_HISTORY_MESSAGES
    return max(MIN_LLM_HISTORY_MESSAGES, min(raw, MAX_LLM_HISTORY_MESSAGES))


def _build_thread_summary(
    slot: str,
    user_id: int,
    history: list[dict],
    qualification: dict | None,
    user_text: str,
) -> str:
    """Structured memory from the whole conversation — prevents out-of-scope replies."""
    from core.dm_store import load_inbox

    qual = qualification or {}
    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    stored = list(conv.get("messages") or [])
    lines: list[str] = [
        f"  - Stored messages in thread: {len(stored)}",
        f"  - Messages passed to you below (oldest→newest): {len(history)}",
        "  - READ every message in order before replying; stay on the active topic only.",
    ]

    human_snips: list[str] = []
    for m in stored[-50:]:
        if m.get("direction") != "out" or m.get("ai"):
            continue
        text = " ".join((m.get("text") or "").split())
        if not text or text.startswith("["):
            continue
        human_snips.append(text[:140])
    if human_snips:
        lines.append("  - Human operator (not AI) already said:")
        for s in human_snips[-4:]:
            lines.append(f"      • {s}")

    constraints: list[str] = []
    if _team_declined_job_support_in_history(history):
        constraints.append(
            "Job support was DECLINED by a human — do NOT re-pitch interview, resume, or Naukri."
        )
    if _job_support_thread_closed(user_text, history):
        constraints.append("Thread is CLOSED after decline — brief ack only or no sales pitch.")
    if _user_requests_india_job_support(user_text, history):
        constraints.append("India job support is NOT sold — say so clearly if asked again.")
    if _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history):
        constraints.append(
            "Support PROVIDER inbound — they offer Java/React/etc. help FOR our candidates, "
            "not seeking a job. Never say 'no job support'. Collect WhatsApp/email; brief ack if contact shared."
        )
    if _is_data_analyst_domain(history, user_text, qual):
        constraints.append("Data/Power BI thread — qualify only; pricing/process → Vani.")
        if _user_wants_proxy_call(user_text, history):
            constraints.append(
                "Power BI proxy — yes supported; ask client/technical + interview date only; "
                "no weekly volume question; pricing → Vani."
            )
    if _user_is_vendor_partner(user_text, history) or _user_is_vendor_partner("", history):
        constraints.append("Vendor/partnership inbound — not a job seeker.")
    if _inbound_looks_like_external_recruitment(user_text, history):
        constraints.append("External recruitment post — not our interview-support line.")

    intent = resolve_thread_intent(history, user_text, qual)
    constraints.append(f"Resolved thread intent: {intent}")
    for key in ("tech_stack", "service_need", "round_type", "interview_timing", "domain"):
        val = (qual.get(key) or "").strip()
        if val and val != "unknown":
            constraints.append(f"Known {key}: {val} — do NOT re-ask")

    if constraints:
        lines.append("  - Mandatory constraints:")
        for c in constraints:
            lines.append(f"      • {c}")

    return "\n".join(lines)


# ── LLM call ────────────────────────────────────────────────────────────────

async def _call_llm(
    *,
    cfg: dict,
    history: list[dict],
    user_text: str,
    lead: dict,
    stage: str,
    qualification: dict,
    slot: str = "",
    user_id: int = 0,
) -> dict:
    from core.ai_llm_gateway import Priority, chat_completion

    intro_allowed = len(history) == 0
    client_lang = _detect_client_language(history, user_text)
    thread_summary = ""
    if slot and user_id:
        thread_summary = _build_thread_summary(
            slot, int(user_id), history, qualification, user_text,
        )
    system_prompt = _build_system_prompt(
        cfg=cfg,
        stage=stage,
        qualification=qualification,
        lead=lead,
        intro_allowed=intro_allowed,
        client_lang=client_lang,
        thread_summary=thread_summary,
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    api_key = _env_api_key()
    api_base = _env_api_base()
    payload = {
        "model": cfg.get("model") or "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.45,
        "max_tokens": 110,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    data = await chat_completion(
        api_base=api_base,
        headers=headers,
        payload=payload,
        priority=Priority.INBOX,
        label=f"inbox:{slot}:{user_id}",
    )
    choice = (data.get("choices") or [{}])[0]
    raw_content = (choice.get("message") or {}).get("content") or "{}"
    out = _parse_llm_output(raw_content)
    if not intro_allowed and not _user_wants_name_in_reply(user_text):
        assistant_name = (cfg.get("assistant_name") or "").strip() or "Karthik"
        out["reply"] = _strip_self_introduction(out.get("reply") or "", assistant_name=assistant_name)
    return out


def _build_system_prompt(
    *,
    cfg: dict,
    stage: str,
    qualification: dict,
    lead: dict,
    intro_allowed: bool,
    client_lang: str = "english",
    thread_summary: str = "",
) -> str:
    from core.ai_smart_reply_store import get_effective_business_prompt

    business = get_effective_business_prompt(cfg)
    cta_link = cfg.get("whatsapp_link") or ""
    cta_label = cfg.get("whatsapp_label") or "WhatsApp"
    payment_upi = (cfg.get("payment_upi_id") or "company@upi").strip()
    assistant_name = (cfg.get("assistant_name") or "").strip() or "Karthik"
    lead_name = (lead.get("name") or "").strip()
    lead_username = (lead.get("username") or "").strip()
    lead_status = (lead.get("status") or "new").strip()

    qual_lines = []
    for k, v in (qualification or {}).items():
        qual_lines.append(f"  - {k}: {v}")
    qualification_block = "\n".join(qual_lines) if qual_lines else "  (nothing known yet)"

    lang_rule = (
        "  - Client writes ENGLISH → reply in ENGLISH ONLY. No Telugu words at all.\n"
        "  - Client writes Telugu → Telugu + English mix is OK.\n"
        if client_lang == "english"
        else "  - Client uses Telugu → Telugu + English mix OK. Match their tone.\n"
    )

    return (
        f"{business}\n\n"
        "## Your identity\n"
        f"  Your name is **{assistant_name}**. You are a real human on our team handling\n"
        "  candidate chats (WhatsApp-style on Telegram). Never reveal you are an AI,\n"
        "  bot, or automated system.\n\n"
        "  Self-introduction rule (STRICT)\n"
        f"  - intro_allowed={str(bool(intro_allowed)).lower()}\n"
        f"  - If intro_allowed=true: introduce yourself ONCE in the very first reply only.\n"
        f"  - If intro_allowed=false: do NOT unprompted say 'This is {assistant_name}' every message.\n"
        f"  - BUT if user asks your name / who are you / human or AI → ALWAYS say '{assistant_name}'\n"
        "    clearly and naturally. Answering your name when asked is REQUIRED, not spam.\n\n"
        "## Lead context\n"
        f"  - Name: {lead_name or '(unknown)'}\n"
        f"  - Username: @{lead_username or '(none)'}\n"
        f"  - CRM status: {lead_status}\n"
        f"  - Current conversation stage: {stage}\n"
        "## Known qualification facts (DO NOT RE-ASK)\n"
        f"{qualification_block}\n"
        + (
            "\n## Full thread memory (read before replying)\n"
            f"{thread_summary}\n"
            if thread_summary.strip()
            else ""
        )
        + "  If tech_stack is listed above → NEVER ask 'which tech stack' again.\n"
        "  If service_need is known → NEVER ask 'what do you need' again.\n"
        "  Ask ONLY the next missing detail — order: tech stack → interview date/time → round type.\n"
        "  When tech is known for interview support, ask date & time BEFORE round type.\n"
        "  If user says interview is NOT YET scheduled / not started → do NOT keep asking date.\n"
        "  SCREENSHOT (STRICT): If they say they HAVE an interview or exam (today, tomorrow, scheduled,\n"
        "  coding test, assessment) → ask them to POST a screenshot of the invite / confirmation here\n"
        "  before payment or slot talk. Skip if they already sent a photo/document in the thread.\n"
        "  If user asks about resume documents / experience letters / docs to keep resume →\n"
        "    treat as Resume Building service — help with documents, NOT interview dates.\n"
        "  If user sends only '.' or punctuation → continue the last topic; never generic filler.\n"
        "  If user says you forgot / same question → apologize briefly + use facts above.\n\n"
        "## Slot + payment order (STRICT)\n"
        "  - NEVER confirm/block/book a slot until client PAID the slot amount.\n"
        "  - BANNED before payment: 'slot confirmed', 'let's block the slot', 'booking done'.\n"
        "  - After payment received → then say slot confirmed for [day/time].\n"
        "  - If user NOT convinced → hand off to senior (never dodge):\n"
        f"    Data/analytics/BI/Power BI → Vani (senior data analyst) 📞 {VANI_PHONE} 📲 {VANI_WHATSAPP}\n"
        "  - Karthik on data/Power BI leads: qualify tech stack + interview timing ONLY.\n"
        "    NEVER quote ₹ amounts or payment — hand off to Vani for pricing/payment/process.\n"
        f"    React/Frontend → Nikhila 📞 {NIKHILA_PHONE} 📲 {NIKHILA_WHATSAPP} | "
        f"Bhavana 📞 {BHAVANA_PHONE} 📲 {BHAVANA_WHATSAPP}\n"
        f"    DevOps/Cloud/SRE → Kalyan 📞 {KALYAN_PHONE} 📲 {KALYAN_WHATSAPP}\n"
        f"    Java / AI-ML / other interview/dev → Thirlok 📞 {THRILOK_PHONE} 📲 {THRILOK_WHATSAPP}\n"
        "  - Data analyst: BI, Power BI, Tableau, SQL, MIS, ETL, Analytics Engineer, etc.\n"
        "  - DevOps: AWS/Azure/GCP DevOps, SRE, Kubernetes, Docker, Terraform, CI/CD, etc.\n"
        "  - Java: Spring Boot, J2EE, Hibernate, Java Full Stack, React+Java, etc.\n"
        "  - AI/ML: AI Engineer, ML Engineer, GenAI, LLM, Data Scientist, MLOps, etc.\n"
        "  - React roles: React Developer, Frontend, MERN, Next.js, UI Developer, etc.\n"
        "  - If user asks HOW assistance works → senior handoff (Vani for data/BI, Kalyan, Nikhila/Bhavana, or Thirlok).\n"
        "  - If confused about free vs paid → apologize + payment-first + senior handoff.\n"
        "  - NEVER skip hard questions with vague 'let me know if you want to proceed'.\n"
        "  - If you don't know or can't close → senior explains. Always share contacts.\n\n"
        "## Conversation stages\n"
        "  1. greeting — warm 1-line opener, ask what they're looking for.\n"
        "  2. qualification — ask 1 short question: experience, tech stack, urgency.\n"
        "  3. value — suggest service + explain how process works. Max 2 lines.\n"
        "  4. cta — user ready to pay: share UPI/payment. Slot confirm ONLY after payment.\n"
        "  5. closed — lead disengaged. Keep replies brief, friendly.\n\n"
        "## Hard rules\n"
        f"{lang_rule}"
        "  - CONCISE (strict): only necessary information — no extra words, no filler, no repetition.\n"
        "    Max 2 short lines OR 1–2 sentences (~25 words). ONE question only if needed.\n"
        "    Pattern: brief ack + one fact/step. Cut everything else.\n"
        "    Good: 'Okay 👍 .NET noted — client or technical?' | Bad: 'Got it…' every message or long intro.\n"
        "  - STYLE: WhatsApp/Telegram — never paragraphs, never bullet lists, never numbered steps.\n"
        "    Never overexplain, never multiple sales lines, never dump catalogue in one message.\n"
        "    Never mention high-volume/custom plans unless the client stated volume (e.g. 40+ calls/week).\n"
        "  - One message only. Max 2 line breaks.\n"
        "  - Vary openers: Okay, Sure, Yes, Noted — do NOT start every reply with 'Got it'.\n"
        "    Never use 'Got it' twice in a row. Often skip the opener entirely.\n"
        "  - Use real operator phrases: 'Okay [Name]', 'Which tech?', 'Send resume'.\n"
        "  - Don't repeat the same line twice in a chat.\n"
        "  - READ the complete message history below (oldest to newest) before every reply.\n"
        "    Never contradict a human operator. Never restart a closed topic.\n"
        "  - NEVER re-ask tech stack, service need, or round type if already in chat\n"
        "    history or Known qualification facts above.\n"
        "  - Ask exactly ONE question when needed — only for info still MISSING.\n"
        "  - Do NOT repeat greetings or intro mid-chat.\n"
        "  - Match client language: English client → English reply only.\n"
        "  - Telugu mix ONLY when client writes Telugu or asks for Telugu.\n"
        "  - NEVER promise guaranteed job, salary, or placement.\n"
        "  - VALUE BEFORE PRICE (strict): when user describes a problem or need, explain HOW the\n"
        "    service fixes their issue first — do NOT quote ₹ amounts unless user asked price/charge\n"
        "    or shows clear interest (interested, proceed, go ahead, tell me price).\n"
        "  - Quote exact catalogue prices ONLY when user asks or shows buy interest. Never invent discounts.\n"
        "  - ABROAD / OUTSIDE INDIA (strict): we do NOT find jobs or arrange interview calls\n"
        "    outside India (no Europe/UK/US job placement, no abroad Naukri call automation).\n"
        "    Abroad we ONLY offer: Resume Building, interview prep, and live interview support\n"
        "    when they already have a scheduled round (abroad round pricing applies).\n"
        "    Never say 'job applications in Europe/UK' or 'help with job searches abroad'.\n"
        "  - JOB SUPPORT (on-the-job / placement-style job support — NOT interview rounds):\n"
        "    INDIA: NOT offered. Say clearly: we do not provide job support in India.\n"
        "    If a human operator already declined job support, do NOT re-pitch interview/resume/Naukri.\n"
        "    NON-DOMESTIC / abroad only: job support when explicitly requested (abroad pricing).\n"
        "  - JOB SEARCH (Naukri / resume / automation calls) — separate from job support:\n"
        "    Resume Building | Naukri Profile Creation | Automation Call Process (India).\n"
        "    If Naukri / not getting calls → explain visibility & calls FIRST. Price only when asked.\n"
        "  - SERVICE PRICING (never mix):\n"
        "    Single interview round → ₹5000 India / ₹8000 abroad.\n"
        "    Interview support TILL OFFER LETTER → ₹1.8 Lakhs total, initial ₹20k.\n"
        "      NOT Job Support. NEVER quote ₹35,000 for till-offer-letter requests.\n"
        "    Job Support abroad (non-domestic) → ₹80,000 when explicitly requested.\n"
        "      NEVER quote ₹35,000 domestic job support — India job support is NOT sold.\n"
        "  - PRICE QUESTION (entha charge / how much / rate): identify service type first,\n"
        "    explain tech team demo + 1 qualifying question (tech/round/date). NEVER say\n"
        "    'expert live on call/WhatsApp during interview' or 'guide chestharu'. NEVER say\n"
        "    'Ready to proceed?' or push payment on first price ask. send_payment_qr=false.\n"
        "  - Payment/UPI/QR ONLY when user explicitly asks how to pay / send UPI / ready to pay.\n"
        "    NEVER on price ask, deferral, identity question, or urgency plea alone.\n"
        "    NEVER confirm slot before payment.\n"
        "  - User defers (Tuesday / later / call after confirm) → soft ack, NO payment push.\n"
        "  - User asks if AI/human → say you're Karthik, real person. Continue the\n"
        "    EXISTING topic (interview/price/Tuesday deferral) — never reset the chat.\n"
        "  - User asks your name / who are you → say 'I'm Karthik 👍' (use their first name\n"
        "    when addressing them, e.g. 'Got it Rahul 👍') then reference what you were\n"
        "    ALREADY discussing. NEVER 'What can I assist you with today?'\n"
        "  - BANNED mid-conversation phrases: 'What can I assist', 'How can I help you\n"
        "    today', 'What do you need help with', 'We were already chatting', starting every reply with 'Haha'.\n"
        "  - NEVER repeat the same reply twice in a row.\n"
        "  - Small talk (how are you, hello) → answer briefly + pivot to what they need.\n"
        "  - Personal questions (where are you, studying in Melbourne) → clarify you're Karthik\n"
        "    from the team in India, then ask what service they need. Do NOT ignore the question.\n"
        "  - User confused ('What?') → apologize + explain clearly, never repeat a vague line.\n"
        "  - ALWAYS use the client's first name when known (from Lead context above).\n"
        "    NEVER use 'bro' — say 'Got it Sathvika 👍' not 'Got it bro 👍'.\n"
        "    If name is unknown, skip the nickname — just 'Got it 👍'.\n"
        "  - CALL REQUEST (want call / discuss on call / connect now / can't chat):\n"
        "    NEVER say 'can't take calls'. Share senior phone + WhatsApp by role:\n"
        f"    Data/Power BI → Vani {VANI_PHONE} | DevOps → Kalyan {KALYAN_PHONE} | "
        f"React → Nikhila/Bhavana | Java/AI/other → Thirlok {THRILOK_PHONE}\n"
        "  - OFFLINE vs ONLINE support: we offer BOTH offline (in-person/on-site) AND online.\n"
        "    NEVER say 'only online', 'fully online only', 'no office visit', or deny offline support.\n"
        "    Short reply: confirm both available + ask city OR preference (one question).\n"
        "  - PROXY / SHADOW CALLER (proxy caller, attend on my behalf, shadow caller):\n"
        "    YES we offer this — expert attends interview on client's behalf. NEVER deny.\n"
        "    NEVER say 'we only provide live support, not shadow callers'. High volume → senior handoff.\n"
        "  - INTERVIEW SUPPORT (how it works): say tech team will give a demo first.\n"
        "    NEVER describe 'expert live on call/WhatsApp during interview' or 'guide chestharu'.\n"
        "  - Lead scoring: Hot (slot/JD ready) → confirm slot; Warm (price ask) → explain\n"
        "    process, no payment push; Cold (vague) → brief prompt.\n"
        "  - Use ALL knowledge: base prompt plus every 'Learned knowledge' block — never ignore older entries.\n"
        f"  - Payment UPI: {payment_upi}. send_payment_qr=true ONLY when user is ready to pay\n"
        "    (how to pay / book / proceed / confirm) — NEVER on first price question.\n"
        "  - DevOps/Cloud/SRE role → qualify briefly; if not convinced → Kalyan handoff.\n"
        "  - Java / AI-ML role → qualify briefly; if not convinced → Thirlok handoff.\n"
        "  - React/Frontend role → qualify briefly; if not convinced → Nikhila/Bhavana handoff.\n"
        "  - Data/analytics/BI/Power BI → Karthik qualifies tech + timing; pricing/payment → Vani handoff.\n"
        "  - Other dev (Node, Angular, general) → Thirlok if not convinced.\n"
        "  - Telegram official login codes (user 777000 / 'Login code: …') → NEVER reply; mark closed/spam.\n"
        "  - Bot broadcasts / agency spam / repeated welcome promos → no reply; next_stage='closed'.\n"
        "    NEVER send 'Okay noted 👍' to Telegram system or login-code messages.\n"
        "  - Every reply must end with a clear next step or soft conclusion — never dead-end or "
        "directionless. Valid ends: slot confirmed, JD/resume requested, call scheduled, waiting "
        "for client, payment pending, support confirmed, spam closed, follow-up scheduled, "
        "not interested, polite close.\n"
        "  - Refunds/discounts/complex issues → 'Let me check and get back to you 👍', escalate=true.\n"
        "  - System shows typing indicator 1–4 sec before send — your reply should feel instant-human.\n"
        "  - Never say 'as an AI'. Never sound corporate or scripted.\n"
        "  - Complex packages: may share "
        f"'{cta_label}: {cta_link}'.\n"
        "  - Out-of-scope → brief decline, pivot. escalate only for refunds/disputes/legal.\n"
        "  - Abusive/spam → one brief reply, next_stage='closed'.\n"
        "  - You are a LIVE inbox operator for ALL eligible chats — never wait for manual\n"
        "    mention of a specific lead. Every real inbound gets handled automatically.\n"
        "  - Prioritize: urgent interviews > active chats > hot leads > follow-ups > stuck unread.\n\n"
        "## Output schema\n"
        "  Reply ONLY with strict JSON, no surrounding prose:\n"
        "  {\n"
        '    "reply": "<concise text, max ~25 words, 1-2 lines>",\n'
        f'    "next_stage": "{STAGE_GREETING}|{STAGE_QUALIFY}|{STAGE_VALUE}|{STAGE_CTA}|{STAGE_CLOSED}",\n'
        '    "extracted_facts": {\n'
        '      "experience": "fresher|0-2y|3-5y|5+y|switching",\n'
        '      "tech_stack": "...", "urgency": "...", "location": "..."\n'
        "    },\n"
        '    "send_payment_qr": false,\n'
        '    "escalate": false,\n'
        '    "confidence": 0.65,\n'
        '    "should_send": true\n'
        "  }\n"
        "  - Only include 'extracted_facts' keys you have new evidence for.\n"
        "  - Set send_payment_qr=true ONLY when user explicitly wants to pay/book — not on price inquiry.\n"
        "  - 'confidence' = how sure you are that 'reply' is appropriate (0–1).\n"
        "  - If should_send=true and reply is non-empty, confidence MUST be >= 0.5.\n"
        "  - 'should_send'=false when there is nothing useful to say.\n"
    )


def _parse_llm_output(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {"reply": "", "should_send": False, "confidence": 0.0}
    # Strip ```json fences if a model added them despite response_format.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0]
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return {"reply": "", "should_send": False, "confidence": 0.0}
        return obj
    except json.JSONDecodeError:
        # Last-ditch: try to extract a JSON object from anywhere in the text.
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {"reply": raw[:200], "should_send": True, "confidence": 0.4}


# ── Safety / sanitization ───────────────────────────────────────────────────

_BANNED_PHRASES = (
    "guaranteed job",
    "100% placement",
    "money back",
    "refund policy",
)


def _typing_delay_seconds(reply_text: str, cfg: dict) -> float:
    """Return a human-like pre-send delay based on reply length."""
    n = len((reply_text or "").strip())
    if n <= 45:
        lo, hi = 0.8, 1.6
    else:
        lo, hi = 1.2, 2.5
    cap_max = float(cfg.get("max_delay_seconds", 4) or 4)
    cap_min = float(cfg.get("min_delay_seconds", 1) or 1)
    hi = min(hi, max(cap_min, cap_max))
    lo = min(lo, hi)
    lo = max(lo, min(cap_min, hi))
    return random.uniform(lo, hi)


async def _simulate_human_typing(slot: str, user_id: int, reply_text: str, cfg: dict) -> None:
    """Show Telegram typing indicator for a natural delay before sending."""
    from core.whatsapp_channel import pick_reply_channel

    if pick_reply_channel(slot, int(user_id)) == "whatsapp":
        return
    delay = _typing_delay_seconds(reply_text, cfg)
    if delay <= 0:
        return
    from services import dm_inbox_service

    await dm_inbox_service.run_dm_typing(slot, int(user_id), delay)


async def _send_payment_qr(slot: str, user_id: int, cfg: dict) -> None:
    """Send the configured payment QR image after a payment-instruction reply."""
    from core.config import BASE_DIR
    from services import dm_inbox_service

    rel = (cfg.get("payment_qr_path") or "data/payment_qr.png").strip()
    path = rel if os.path.isabs(rel) else os.path.join(BASE_DIR, rel)
    if not os.path.isfile(path):
        logger.warning("payment QR file missing: %s", path)
        return
    await dm_inbox_service.run_dm_send_photo(
        slot,
        int(user_id),
        path,
        caption="",
        sent_by="ai",
    )


def _sanitize_reply(
    text: str,
    cfg: dict,
    *,
    history: list[dict] | None = None,
) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    s = _vary_got_it_opener(s, history)
    s = _enforce_short_reply(s)
    # Strip out any banned promises the model snuck in.
    lower = s.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lower:
            return ""
    return s


def _strip_self_introduction(text: str, *, assistant_name: str) -> str:
    """Remove repeated self-introductions from a reply.

    This is a last-line guardrail for when the model ignores the prompt.
    We only call this when the conversation already has history.
    """
    s = (text or "").strip()
    if not s:
        return ""

    name = (assistant_name or "").strip()
    if not name:
        return s

    # Common intro patterns near the start of a message.
    # Examples:
    #   "Hey! This is Karthik — ..."
    #   "Hi, I'm Karthik."
    #   "Karthik here, ..."
    intro_re = re.compile(
        r"^\s*(hey|hi|hello)?\s*[!,. ]*\s*(this is|i am|i'm|im|we are|we're)?\s*"
        + re.escape(name)
        + r"(\s+here)?\s*([\-–—,:]|\.|\!)?\s*",
        re.IGNORECASE,
    )

    s2 = intro_re.sub("", s, count=1).strip()

    # Also strip embedded "this is <name>" phrases if they appear later.
    embedded_re = re.compile(r"\b(this is|i am|i'm|im)\s+" + re.escape(name) + r"\b", re.IGNORECASE)
    s2 = embedded_re.sub("", s2).strip()

    # Avoid leaving a leading dash/comma after stripping.
    s2 = re.sub(r"^[\-–—,:]+\s*", "", s2).strip()
    return s2 or s


# ── Helpers --------------------------------------------------------------------

def _is_last_outbound_human(slot: str, user_id: int) -> bool:
    """Return True iff the most recent outbound message was typed by a human
    (i.e. not tagged with ``ai=True``).

    Used by the human-pause gate to avoid the AI blocking itself: `last_reply_at`
    on the lead record advances whenever *any* outbound message goes out, but
    we only want to pause when the operator is actually engaged.
    """
    from core.dm_store import load_inbox

    data = load_inbox(slot) or {}
    conv = (data.get("conversations") or {}).get(str(int(user_id))) or {}
    msgs = conv.get("messages") or []
    for m in reversed(msgs):
        if m.get("direction") == "out":
            return not bool(m.get("ai"))
    return False


def _recent_conversation(slot: str, user_id: int, *, limit: int = 12) -> list[dict]:
    """Map the last N stored messages into OpenAI chat-completions format.
    Inbound messages → role=user, outbound → role=assistant. System messages
    (e.g. the "new" placeholder) are skipped."""
    from core.dm_store import load_inbox

    data = load_inbox(slot) or {}
    conv = (data.get("conversations") or {}).get(str(int(user_id)))
    if not conv:
        return []
    msgs = list(conv.get("messages") or [])[-limit:]
    out: list[dict] = []
    for m in msgs:
        d = m.get("direction")
        text = (m.get("text") or "").strip()
        if not text or d not in {"in", "out"}:
            continue
        role = "user" if d == "in" else "assistant"
        out.append({"role": role, "content": text})
    return out


def _tag_message_as_ai(slot: str, user_id: int, message_id: int, *, stage: str, confidence: float) -> None:
    """Mark a persisted outbound record as AI-generated so the UI badges it."""
    from core.dm_store import _apply_outbound_meta, load_inbox, save_inbox

    data = load_inbox(slot) or {}
    conv = (data.get("conversations") or {}).get(str(int(user_id)))
    if not conv:
        return
    msgs = conv.get("messages") or []
    for m in msgs:
        if int(m.get("id") or 0) == int(message_id):
            _apply_outbound_meta(
                m,
                sent_by="ai",
                sender_name="AI",
                ai=True,
                ai_stage=stage,
                ai_confidence=confidence,
            )
            break
    save_inbox(slot, data)


async def _broadcast_escalation(slot: str, user_id: int, *, reason: str) -> None:
    """Tell connected dashboards that a lead now needs human attention."""
    try:
        from events.event_bus import event_bus
        from events.event_types import EventType

        await event_bus.publish(
            EventType.MESSAGE_RECEIVED,
            slot,
            {
                "user_id": int(user_id),
                "ai_escalated": True,
                "reason": reason,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            push_state=False,
        )
    except Exception:
        pass


def list_pending_inbound_targets(*, slot_filter: str | None = None) -> list[dict]:
    """Conversations whose last message is inbound and still needs a reply."""
    from core.config import ACCOUNTS
    from core.crm_store import get_lead
    from core.dm_store import load_inbox

    from core.block_store import is_blocked

    inactive = {"spam", "converted", "not_interested"}
    slots = [slot_filter] if slot_filter else list(ACCOUNTS)
    out: list[dict] = []
    for slot in slots:
        if slot not in ACCOUNTS:
            continue
        data = load_inbox(slot)
        for uid, conv in (data.get("conversations") or {}).items():
            try:
                user_id = int(uid)
            except (TypeError, ValueError):
                continue
            msgs = list(conv.get("messages") or [])
            if not msgs or msgs[-1].get("direction") != "in":
                continue
            last = msgs[-1]
            text = (last.get("text") or "").strip()
            if not text:
                continue
            if is_blocked(slot, user_id):
                continue
            from core.spam_detector import is_telegram_service_chat

            if is_telegram_service_chat(
                (last.get("text") or "").strip(),
                name=conv.get("name") or "",
                username=conv.get("username") or "",
                user_id=user_id,
            ):
                continue
            lead = get_lead(slot, user_id) or {}
            if (lead.get("status") or "").lower() in inactive:
                continue
            ai_state = get_lead_state(slot, user_id)
            ai_state = _karthik_resume_waiting_client(slot, user_id, ai_state)
            if not ai_state.get("enabled", True):
                continue
            disable_reason = (ai_state.get("_disable_reason") or "").strip()
            if disable_reason in _AI_DISABLE_STICKY_REASONS:
                continue
            try:
                from services.crm_service import _unanswered_elapsed_seconds

                if _unanswered_elapsed_seconds(lead, slot=slot, user_id=user_id) is None:
                    continue
            except Exception:
                pass
            age_sec = None
            ts = conv.get("last_message_at") or last.get("timestamp")
            if ts:
                try:
                    age_sec = int(max(0, time.time() - datetime.fromisoformat(
                        str(ts).replace("Z", "+00:00")
                    ).timestamp()))
                except (TypeError, ValueError):
                    age_sec = None
            out.append({
                "slot": slot,
                "user_id": user_id,
                "name": conv.get("name") or uid,
                "message_id": last.get("id"),
                "text": text,
                "age_sec": age_sec,
            })
    return out


async def catch_up_pending_replies(
    *,
    slot: str | None = None,
    force: bool = True,
    max_replies: int = 25,
) -> dict:
    """Reply to unanswered inbound chats — used after outages or manual wake."""
    from core.ai_smart_reply_store import get_config, update_config

    cfg = get_config()
    patch: dict = {}
    if not cfg.get("enabled"):
        patch["enabled"] = True
    if (str(cfg.get("mode") or "auto")).strip().lower() != "auto":
        patch["mode"] = "auto"
    if patch:
        update_config(**patch)

    from messaging.message_router import message_router

    targets = list_pending_inbound_targets(slot_filter=slot)[: max(1, int(max_replies or 25))]
    results: list[dict] = []
    ok = fail = 0
    from messaging.account_queue import queue_manager

    for t in targets:
        try:
            uid = int(t["user_id"])
            slot_id = t["slot"]
            if await queue_manager.get_queue(slot_id).has_pending_ai_auto_reply_for_user(uid):
                results.append({**t, "ok": False, "reason": "already_queued"})
                continue
            if _recent_outbound_within_sec(slot_id, uid, seconds=75):
                results.append({**t, "ok": False, "reason": "recent_outbound"})
                continue
            if _inbound_looks_like_outbound_echo(t.get("text") or ""):
                results.append({**t, "ok": False, "reason": "outbound_echo"})
                continue
            await message_router.enqueue_ai_auto_reply(
                slot_id,
                uid,
                user_message_id=t.get("message_id"),
                user_text=t["text"],
                force=force,
            )
            row = {**t, "ok": True, "reason": "enqueued"}
            results.append(row)
            ok += 1
            _monitor("ai_scheduled", slot=t["slot"], user_id=t["user_id"], reason="catch_up")
        except Exception as e:
            fail += 1
            results.append({**t, "ok": False, "reason": "enqueue_error", "error": str(e)[:200]})
        await asyncio.sleep(0.2)
    return {
        "status": "ok",
        "pending_found": len(list_pending_inbound_targets(slot_filter=slot)),
        "attempted": len(targets),
        "enqueued": ok,
        "failed": fail,
        "mode": get_config().get("mode"),
        "enabled": get_config().get("enabled"),
        "results": results,
    }


# ── Playbooks (config/karthik/) override hardcoded defaults at import ───────
from core.karthik import playbooks as _karthik_playbooks

_karthik_playbooks.apply_to_ai_module(globals())
