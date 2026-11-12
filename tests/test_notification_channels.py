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


def test_only_accepted_whatsapp_sends_count_as_deliveries(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from features import service_inbox, web_push
    from services import whatsapp_bsp
    import main

    sent: list[str] = []

    class FakeClient:
        configured = True

        async def send_text(self, phone, text):
            sent.append(phone)
            return {"ok": phone.endswith("1"), "status_code": None if phone.endswith("1") else 400}

    monkeypatch.setenv("DASHBOARD_PASSWORD", "dashboard-fixture")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "service-fixture")
    monkeypatch.setenv("WHATSAPP_SLOTS_NOTIFY_PHONES", "+910000000001, +910000000002")
    monkeypatch.setattr(service_inbox, "_PATH", str(tmp_path / "inbox.json"))
    monkeypatch.setattr(web_push, "all_usernames_with_subscriptions", lambda: [])
    monkeypatch.setattr(whatsapp_bsp, "get_bsp_client", lambda: FakeClient())

    response = TestClient(main.app).post(
        "/internal/v1/notifications",
        json={"title": "Fixture", "body": "b", "tag": "t", "whatsapp_text": "hello"},
        headers={"X-Internal-Service-Token": "service-fixture", "X-Idempotency-Key": "wa-count"},
    )
    assert response.status_code == 200
    assert sent == ["+910000000001", "+910000000002"]
    assert response.json()["whatsapp_deliveries"] == 1
