"""ops-watch #181: in-app notifications reached nobody on either channel."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_ships_the_push_service_worker():
    # webPush.js registers /sw.js. Without the file the SPA fallback answered
    # with index.html, browsers refused an HTML service worker, and no device
    # could ever subscribe. Vite copies dashboard/public into static/.
    sw = (ROOT / "dashboard" / "public" / "sw.js").read_text(encoding="utf-8")
    assert "addEventListener('push'" in sw
    assert "showNotification" in sw
    assert "push-open-chat" in sw  # what subscribePushOpenChat listens for
    assert (ROOT / "dashboard" / "public" / "favicon.svg").is_file()  # the notification icon


def test_production_compose_passes_the_alert_numbers_through():
    compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert "WHATSAPP_SLOTS_NOTIFY_PHONES: ${WHATSAPP_SLOTS_NOTIFY_PHONES:-}" in compose


import pytest


class FakeClient:
    configured = True

    def __init__(self, *, refuse=(), raise_for=()):
        self.calls: list[tuple] = []
        self.refuse, self.raise_for = set(refuse), set(raise_for)

    async def _go(self, kind, phone, payload):
        self.calls.append((kind, phone, payload))
        if phone in self.raise_for:
            raise RuntimeError("boom")
        return {"ok": phone not in self.refuse}

    async def send_text(self, phone, text):
        return await self._go("text", phone, text)

    async def send_template(self, phone, name, params, *, language_code="en"):
        return await self._go("template", phone, (name, tuple(params), language_code))


@pytest.fixture
def notify(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from features import service_inbox, web_push
    from services import whatsapp_bsp
    import main

    monkeypatch.setenv("DASHBOARD_PASSWORD", "dashboard-fixture")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "service-fixture")
    monkeypatch.setenv("WHATSAPP_SLOTS_NOTIFY_PHONES", "+910000000001, +910000000002")
    monkeypatch.delenv("WHATSAPP_ALERT_TEMPLATE", raising=False)
    monkeypatch.setattr(service_inbox, "_PATH", str(tmp_path / "inbox.json"))
    monkeypatch.setattr(web_push, "all_usernames_with_subscriptions", lambda: [])
    state = {"client": FakeClient()}
    monkeypatch.setattr(whatsapp_bsp, "get_bsp_client", lambda: state["client"])
    http = TestClient(main.app)

    def post(key="k1", text="hello"):
        return http.post(
            "/internal/v1/notifications",
            json={"title": "Fixture", "body": "b", "tag": "t", "whatsapp_text": text},
            headers={"X-Internal-Service-Token": "service-fixture", "X-Idempotency-Key": key},
        )

    post.state = state
    return post


def test_only_accepted_whatsapp_sends_count_as_deliveries(notify):
    notify.state["client"] = FakeClient(refuse={"+910000000002"})
    response = notify()
    assert response.status_code == 200
    assert response.json()["whatsapp_deliveries"] == 1
    assert response.json()["whatsapp_failures"] == 1


def test_alerts_use_the_approved_template_when_configured(notify, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ALERT_TEMPLATE", "ops_alert")
    response = notify(text="Interview booked\n\nCandidate:   A\tB")
    assert response.json()["whatsapp_mode"] == "template"
    kinds = {c[0] for c in notify.state["client"].calls}
    assert kinds == {"template"}
    name, params, lang = notify.state["client"].calls[0][2]
    assert (name, lang) == ("ops_alert", "en")
    assert params == ("Interview booked | Candidate: A B",)  # no newline, tab or long space run


def test_a_retry_never_repeats_an_alert_someone_already_got(notify):
    notify.state["client"] = FakeClient(raise_for={"+910000000002"})
    first = notify(key="partial")
    assert first.status_code == 200 and first.json()["whatsapp_deliveries"] == 1
    assert notify(key="partial").json()["status"] == "duplicate"
    assert [c[1] for c in notify.state["client"].calls] == ["+910000000001", "+910000000002"]


def test_nothing_delivered_is_not_confirmed_and_can_be_retried(notify):
    notify.state["client"] = FakeClient(refuse={"+910000000001", "+910000000002"})
    first = notify(key="refused")
    assert first.status_code == 503 and first.json()["status"] == "undelivered"
    notify.state["client"] = FakeClient()
    second = notify(key="refused")
    assert second.status_code == 200 and second.json()["whatsapp_deliveries"] == 2


def test_no_recipients_is_not_an_error(notify, monkeypatch):
    monkeypatch.setenv("WHATSAPP_SLOTS_NOTIFY_PHONES", "")
    response = notify(key="nobody")
    assert response.status_code == 200 and response.json()["attempted"] == 0


def test_interakt_2xx_with_result_false_is_a_refusal(monkeypatch):
    import asyncio
    import httpx
    from services import whatsapp_interakt as wi

    def handler(request):
        return httpx.Response(200, json={"result": False, "message": "No approved template found"})

    real = httpx.AsyncClient
    monkeypatch.setattr(wi.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    client = wi.InteraktClient(api_key="k")
    assert asyncio.run(client.send_template("+910000000001", "ops_alert", ["x"]))["ok"] is False
    assert asyncio.run(client.send_text("+910000000001", "x"))["ok"] is False
