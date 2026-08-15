from core.karthik.thread_intent import (
    INTENT_DEV_COLLAB,
    INTENT_INTERVIEW,
    INTENT_JOB_SEARCH,
    resolve_thread_intent,
)


def test_thread_intent_classifies_core_messaging_leads():
    assert resolve_thread_intent([], "I need help preparing for a technical interview") == INTENT_INTERVIEW
    assert resolve_thread_intent([], "I am looking for job placement") == INTENT_JOB_SEARCH
    assert resolve_thread_intent([], "Interested in developer collaboration") == INTENT_DEV_COLLAB


def test_saved_thread_intent_is_stable():
    assert resolve_thread_intent([], "job search", {"thread_intent": INTENT_INTERVIEW}) == INTENT_INTERVIEW
