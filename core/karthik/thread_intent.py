"""Deterministic intent guardrails used before generating a smart reply."""

from __future__ import annotations

INTENT_UNKNOWN = "unknown"
INTENT_JOB_SEARCH = "job_search"
INTENT_INTERVIEW = "interview_support"
INTENT_INTERVIEW_TILL_OFFER = "interview_till_offer"
INTENT_DEV_COLLAB = "developer_collaboration"
INTENT_PROXY = "proxy_interview"


def user_blob(history: list[dict] | None, user_text: str = "") -> str:
    values = [str(item.get("content") or "") for item in (history or []) if str(item.get("role") or "").lower() in {"user", "human", "client"}]
    values.append(user_text or "")
    return " ".join(values).lower()


def resolve_thread_intent(history: list[dict] | None, user_text: str = "", qualification: dict | None = None) -> str:
    saved = str((qualification or {}).get("thread_intent") or "").strip()
    if saved in {INTENT_JOB_SEARCH, INTENT_INTERVIEW, INTENT_INTERVIEW_TILL_OFFER, INTENT_DEV_COLLAB, INTENT_PROXY}:
        return saved
    blob = user_blob(history, user_text)
    if any(term in blob for term in ("proxy interview", "attend interview for", "take my interview")): return INTENT_PROXY
    if any(term in blob for term in ("till offer", "until offer", "job support through offer")): return INTENT_INTERVIEW_TILL_OFFER
    if any(term in blob for term in ("interview", "mock round", "technical round")): return INTENT_INTERVIEW
    if any(term in blob for term in ("developer collaboration", "project partner", "freelance developer")): return INTENT_DEV_COLLAB
    if any(term in blob for term in ("looking for job", "job search", "need a job", "placement")): return INTENT_JOB_SEARCH
    return INTENT_UNKNOWN


def has_interview_context(intent_or_history, user_text: str = "") -> bool:
    intent = intent_or_history if isinstance(intent_or_history, str) else resolve_thread_intent(intent_or_history, user_text)
    return intent in {INTENT_INTERVIEW, INTENT_INTERVIEW_TILL_OFFER, INTENT_PROXY}


def intent_blocks_dev_collab(intent: str) -> bool: return intent in {INTENT_JOB_SEARCH, INTENT_INTERVIEW, INTENT_INTERVIEW_TILL_OFFER, INTENT_PROXY}
def intent_blocks_job_search(intent: str) -> bool: return intent in {INTENT_DEV_COLLAB, INTENT_INTERVIEW, INTENT_INTERVIEW_TILL_OFFER, INTENT_PROXY}
def intent_blocks_generic_menu(intent: str) -> bool: return intent != INTENT_UNKNOWN
def intent_is_locked(intent: str) -> bool: return intent != INTENT_UNKNOWN


def service_need_for_intent(intent: str) -> str:
    return {INTENT_JOB_SEARCH: "job_search", INTENT_INTERVIEW: "interview_support", INTENT_INTERVIEW_TILL_OFFER: "interview_support", INTENT_PROXY: "interview_support", INTENT_DEV_COLLAB: "developer_collaboration"}.get(intent, "")
