"""The Operations bridge must outlast the slow slot routes it proxies.

The booking form reads an interview invite with a model and tells the
candidate it "may take a few minutes".  A 60s ceiling on every proxied call
cut that off, and the cutoff surfaced as an error the form still reported as
a successful booking, so a slot the candidate believed was booked never
existed.
"""

import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.business_compatibility import _timeout_for, install_business_compatibility


SLOW = 300.0
DEFAULT = 60.0


@pytest.mark.parametrize("path", [
    "public/slots/extract-invite-ai",
    "public/slots/extract-resume-ai",
    "public/slots/extract-payment-ai",
    "public/slots/parse-screenshot",
    "public/slots/book",
])
def test_ai_assisted_slot_routes_get_the_long_timeout(path: str) -> None:
    assert _timeout_for(path) == SLOW


@pytest.mark.parametrize("path", [
    "public/slots/booked",
    "public/slots/candidates",
    "candidates/interviews/slots",
    "data-room",
])
def test_ordinary_routes_keep_the_default_timeout(path: str) -> None:
    assert _timeout_for(path) == DEFAULT


def test_listing_booked_slots_is_not_treated_as_the_confirm(monkeypatch) -> None:
    """`/book` is slow; `/booked` is the list that must stay quick."""
    assert _timeout_for("public/slots/book") == SLOW
    assert _timeout_for("public/slots/booked") == DEFAULT


def test_both_timeouts_are_configurable(monkeypatch) -> None:
    monkeypatch.setenv("OPERATIONS_PROXY_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("OPERATIONS_PROXY_SLOW_TIMEOUT_SECONDS", "45")
    assert _timeout_for("public/slots/booked") == 5.0
    assert _timeout_for("public/slots/book") == 45.0


def test_a_timeout_becomes_504_not_a_silent_failure(monkeypatch) -> None:
    """A cutoff must reach the caller as a gateway timeout it can act on."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-token")
    monkeypatch.setenv("OPERATIONS_INTERNAL_URL", "http://operations-api:8000")

    class TimingOutClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, *a, **kw):
            raise httpx.ReadTimeout("upstream took too long")

    monkeypatch.setattr(httpx, "AsyncClient", TimingOutClient)

    app = FastAPI()
    install_business_compatibility(app)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/public/slots/book", json={"client": "Sailaja Chennu"}
    )

    assert response.status_code == 504
    assert "did not answer" in response.json()["detail"]
