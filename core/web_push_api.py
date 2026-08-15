"""HTTP routes for Web Push (register on app from server.py)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


def _subscription_fields(sub: dict[str, Any]) -> tuple[str, str, str] | None:
    if not isinstance(sub, dict):
        return None
    endpoint = str(sub.get("endpoint") or "").strip()
    keys = sub.get("keys") if isinstance(sub.get("keys"), dict) else {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        return None
    return endpoint, p256dh, auth


def install_web_push_routes(app) -> None:
    from core import dashboard_auth as auth
    from features import web_push

    @app.get("/push/vapid-public-key")
    async def push_vapid_public_key():
        pub = web_push.public_vapid_key()
        if not pub:
            return {"status": "error", "message": "Web Push not configured on server"}
        return {"status": "ok", "public_key": pub}

    @app.post("/push/subscribe")
    async def push_subscribe(request: Request, body: dict | None = None):
        username = auth.username_from_request_cookies(dict(request.cookies)) or ""
        if not username:
            return JSONResponse({"status": "error", "detail": "Authentication required"}, status_code=401)
        payload = body or {}
        sub = payload.get("subscription") if isinstance(payload.get("subscription"), dict) else payload
        fields = _subscription_fields(sub if isinstance(sub, dict) else {})
        if not fields:
            return {"status": "error", "message": "Invalid subscription"}
        endpoint, p256dh, key_auth = fields
        ua = request.headers.get("user-agent")
        profile = auth.operator_profile_from_cookies(dict(request.cookies))
        return web_push.register_subscription(
            username=username,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=key_auth,
            user_agent=ua,
            role=profile.get("role") or "admin",
        )

    @app.delete("/push/subscribe")
    async def push_unsubscribe(request: Request, body: dict | None = None):
        username = auth.username_from_request_cookies(dict(request.cookies)) or ""
        if not username:
            return JSONResponse({"status": "error", "detail": "Authentication required"}, status_code=401)
        payload = body or {}
        sub = payload.get("subscription") if isinstance(payload.get("subscription"), dict) else payload
        endpoint = ""
        if isinstance(sub, dict):
            endpoint = str(sub.get("endpoint") or "").strip()
        if not endpoint:
            endpoint = str(payload.get("endpoint") or "").strip()
        removed = web_push.unregister_subscription(username=username, endpoint=endpoint)
        return {"status": "ok", "removed": removed}
