"""Two endpoints that returned HTTP 500 on the first hosted staging walkthrough.

Neither was covered by a test, and neither was reachable from the UI before
Groups Upload was restored, so both survived every previous gate: unit tests,
container health checks, and the dual-service contract suite all passed while
these 500'd.

Both faults were latent in the monolith too. They are regression-locked here
because the split now has UI that reaches them.
"""

from __future__ import annotations

import importlib

import pytest


def test_account_state_has_no_bare_success_list():
    """The attribute main.py used to read does not exist, and must not be assumed.

    AccountState exposes campaign_/forwarding_-prefixed lists, and surfaces bare
    success_list/failed_list only as keys of the snapshot dict it builds. Reading
    them off the object raises AttributeError, which is exactly what took
    /groups/lists down.
    """
    from workers.account_state import AccountState

    state = AccountState(slot="account1")
    assert not hasattr(state, "success_list")
    assert not hasattr(state, "failed_list")
    # The real storage the endpoint must read instead.
    assert hasattr(state, "campaign_success_list")
    assert hasattr(state, "campaign_failed_list")
    assert hasattr(state, "forwarding_failed_list")


def test_group_lists_reads_the_attributes_that_exist():
    """A fresh AccountState must yield empty cycle lists, not an AttributeError."""
    from workers.account_state import AccountState

    st = AccountState(slot="account1")
    # Mirrors the access pattern in main.get_group_lists.
    cycle_success = list(getattr(st, "campaign_success_list", None) or [])
    raw_failed = (
        list(getattr(st, "campaign_failed_list", None) or [])
        or list(getattr(st, "forwarding_failed_list", None) or [])
    )
    assert cycle_success == []
    assert raw_failed == []

    st.campaign_success_list.append("some_group")
    st.campaign_failed_list.append({"group": "other", "reason": "flood"})
    assert list(st.campaign_success_list) == ["some_group"]
    assert [
        {"group": x.get("group", ""), "reason": x.get("reason", "")}
        for x in st.campaign_failed_list
        if isinstance(x, dict)
    ] == [{"group": "other", "reason": "flood"}]


def test_ai_smart_reply_health_survives_the_missing_group_message_module():
    """health() must not 500 because an optional capability module is absent.

    core.ai_group_message exists in neither this repository nor the monolith, so
    the unguarded import made the whole smart-reply config endpoint fail.
    """
    # Both of these are absent from this repo and from the monolith.
    for absent in ("core.ai_group_message", "core.ai_work_hours"):
        with pytest.raises(ImportError):
            importlib.import_module(absent)

    from core import ai_smart_reply

    result = ai_smart_reply.health()
    assert isinstance(result, dict)
    # Degrades to "not ready" rather than raising.
    assert result.get("group_rewrite_ready") is False
    assert isinstance(result.get("work_hours"), dict)
    # The rest of the payload is still produced.
    assert "enabled" in result
    assert "api_key_present" in result
