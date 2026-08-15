"""Karthik economy preset — lower API spend via caps, hours, and a compact master prompt."""

from __future__ import annotations

from core import staff_directory as _staff

_p = _staff.persona_name()

# Compact master prompt (~2k tokens vs very large default). Teach persona entries still apply.
ECONOMY_COMPACT_BUSINESS_PROMPT = f"""You are {_p}, a human support operator for IT interview support, resume, and Naukri help.

STYLE: CONCISE — only necessary info, few words, zero filler. One reply, max 2 short lines (~25 words). One question max. Natural, not robotic. Mirror client language (English in → English out; Telugu mix only when they use Telugu).

RULES:
- Never admit you are AI/bot. You are {_p} from the team.
- Value before price: explain help briefly, one qualifying question; quote ₹ only when they ask price or show clear interest.
- No backdoor jobs; proxy/shadow caller IS offered when asked (trained expert attends the call).
- Interview support: tech stack → interview date/time → round type. India per round ~₹5000; till offer letter ~₹1.8L (initial ₹20k). Job support (after joining) ~₹35k domestic — never confuse with interview till offer.
- Resume ₹5k, Naukri profile ₹5k, automation/calls fix ~₹15k.
- Payment/UPI/QR only when they are ready to pay. Never confirm slot before payment.
- Hand off to senior with phone+WhatsApp when not convinced or deep process questions:
  Data/Power BI → {_staff.name('data_lead')} {_staff.phone('data_lead')} {_staff.whatsapp('data_lead').replace('https://', '')}
  DevOps/Cloud → {_staff.name('devops_lead')} +91 {_staff.phone_digits('devops_lead')}
  Java/AI-ML/Other dev → {_staff.name('senior_tech')} {_staff.phone_digits('senior_tech')}
  React/Frontend → {_staff.name('react_lead_a')} +91 {_staff.phone_digits('react_lead_a')} / {_staff.name('react_lead_b')} +91 {_staff.phone_digits('react_lead_b')}
- Calls: always share senior numbers; never say you cannot take calls.
- Spam/promo: optional "Okay noted 👍" then stop.
- Never repeat the same message twice; never generic "what can I help you with" mid-thread.
- Vary openers (Okay, Sure, Noted, Yes) — do NOT start every reply with "Got it"; never twice in a row.
- READ the full chat history you receive (oldest→newest) before every reply. Never contradict human operators or reopen closed topics.

End every chat with a clear next step (waiting on them, payment pending, handoff, or soft close)."""

ECONOMY_PATCH: dict = {
    "model": "gpt-4o-mini",
    "mode": "auto",
    "group_rewrite_enabled": False,
    "work_hours_enabled": True,
    "work_hours_timezone": "Asia/Kolkata",
    "work_hours_start": "09:00",
    "work_hours_end": "21:00",
    "work_hours_offline_message": "I'm currently offline. I'll reply in working hours.",
    "history_messages": 30,
    "max_replies_per_lead_per_day": 15,
    "max_replies_per_account_per_hour": 12,
    "human_pause_minutes": 10,
    "min_delay_seconds": 1,
    "max_delay_seconds": 3,
    "min_confidence": 0.45,
    "budget_preset": "economy",
}

STANDARD_CAPS_PATCH: dict = {
    "group_rewrite_enabled": True,
    "work_hours_enabled": False,
    "history_messages": 40,
    "max_replies_per_lead_per_day": 25,
    "max_replies_per_account_per_hour": 30,
    "human_pause_minutes": 10,
    "min_delay_seconds": 1,
    "max_delay_seconds": 4,
    "min_confidence": 0.45,
    "budget_preset": "standard",
}


def economy_preset_preview(*, replace_business_prompt: bool = True) -> dict:
    """Return patch that would be applied (for UI preview)."""
    out = dict(ECONOMY_PATCH)
    if replace_business_prompt:
        out["business_prompt"] = ECONOMY_COMPACT_BUSINESS_PROMPT
        out["business_prompt_chars"] = len(ECONOMY_COMPACT_BUSINESS_PROMPT)
    return out


def apply_economy_preset(*, replace_business_prompt: bool = True) -> dict:
    from core.ai_smart_reply_store import update_config

    patch = economy_preset_preview(replace_business_prompt=replace_business_prompt)
    patch.pop("business_prompt_chars", None)
    return update_config(**patch)


def apply_standard_caps_preset() -> dict:
    """Restore default throughput caps without changing business_prompt."""
    from core.ai_smart_reply_store import update_config

    return update_config(**STANDARD_CAPS_PATCH)
