from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core import crm_store, dashboard_auth_vps, knowledge_assistant


def test_marketing_auth_accepts_only_configured_admin(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "marketing-admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct-password")

    assert dashboard_auth_vps.resolve_operator_login("marketing-admin", "correct-password") == {
        "username": "marketing-admin",
        "role": "admin",
        "reference": None,
    }
    assert dashboard_auth_vps.resolve_operator_login("handler", "correct-password") is None


def test_marketing_session_rejects_non_admin_role(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct-password")
    token = dashboard_auth_vps.create_session_token("legacy-handler", role="handler", reference="Example")

    assert dashboard_auth_vps.parse_session_token(token) is None


def test_marketing_assistant_reads_only_crm_leads(monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    monkeypatch.setattr(knowledge_assistant, "_ollama_plan", lambda *_: None)
    monkeypatch.setattr(
        crm_store,
        "list_leads",
        lambda: {
            "account1:1": {
                "name": "Example Lead",
                "status": "interested",
                "account_id": "account1",
                "last_contact_time": old,
            },
            "account1:2": {
                "name": "Closed Lead",
                "status": "converted",
                "account_id": "account1",
                "last_contact_time": old,
            },
        },
    )

    result = knowledge_assistant.answer_question("Which leads had no reply for two days?")

    assert result["status"] == "ok"
    assert result["plan"] == {"intent": "stale_leads", "days": 2}
    assert result["evidence_count"] == 1
    assert result["evidence"][0]["title"] == "Example Lead"


def test_internal_contract_uses_service_auth_with_dashboard_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from features import service_inbox
    import main

    monkeypatch.setenv("DASHBOARD_PASSWORD", "dashboard-fixture")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "service-fixture")
    monkeypatch.setattr(service_inbox, "_PATH", str(tmp_path / "inbox.json"))
    client = TestClient(main.app)
    assert client.post("/internal/v1/notifications", json={}).status_code == 401
    response = client.post(
        "/internal/v1/notifications",
        json={"title": "Fixture", "body": "sanitized", "tag": "test"},
        headers={"X-Internal-Service-Token": "service-fixture", "X-Idempotency-Key": "auth-test"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_marketing_websocket_requires_admin_session_and_cleans_up(monkeypatch):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from core import broadcast
    import main

    monkeypatch.setenv("DASHBOARD_PASSWORD", "dashboard-fixture")
    monkeypatch.setenv("DASHBOARD_AUTH_SECRET", "websocket-fixture-secret")
    client = TestClient(main.app)

    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("/ws"):
            pass
    assert denied.value.code == 4403

    token = dashboard_auth_vps.create_session_token("marketing-admin")
    baseline = len(broadcast.active_connections)
    with client.websocket_connect(
        "/ws",
        headers={"cookie": f"{dashboard_auth_vps.SESSION_COOKIE}={token}"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "state"
        assert len(broadcast.active_connections) == baseline + 1
    assert len(broadcast.active_connections) == baseline
