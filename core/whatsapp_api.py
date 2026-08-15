"""HTTP routes for WhatsApp Business CRM (register on app from server.py)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger(__name__)


def install_whatsapp_routes(app) -> None:
    @app.get("/webhooks/whatsapp")
    async def whatsapp_webhook_verify(request: Request):
        from services.whatsapp_bsp import verify_webhook_challenge

        params = request.query_params
        challenge = verify_webhook_challenge(
            params.get("hub.mode"),
            params.get("hub.verify_token"),
            params.get("hub.challenge"),
        )
        if challenge is None:
            return PlainTextResponse("Forbidden", status_code=403)
        return PlainTextResponse(str(challenge))

    @app.post("/webhooks/whatsapp")
    async def whatsapp_webhook_ingest(request: Request):
        from core.config import is_whatsapp_enabled
        from services.whatsapp_bsp import verify_interakt_signature
        from services.whatsapp_inbox_service import process_webhook_payload

        if not is_whatsapp_enabled():
            return {"status": "ok", "ignored": "whatsapp_disabled"}

        raw = await request.body()
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            payload = {}

        import os

        from core import dashboard_auth_vps as dash_auth

        secret = os.environ.get("WHATSAPP_WEBHOOK_SECRET", "").strip()
        if not secret:
            if dash_auth.auth_enabled():
                logger.warning("WhatsApp webhook rejected — WHATSAPP_WEBHOOK_SECRET not set")
                return JSONResponse(
                    {"status": "error", "message": "Webhook secret not configured"},
                    status_code=503,
                )
            logger.warning("WhatsApp webhook accepted without signature (dev only)")
        else:
            sig = request.headers.get("Interakt-Signature") or request.headers.get("X-Hub-Signature-256")
            if not verify_interakt_signature(raw, sig, secret):
                logger.warning("WhatsApp webhook signature mismatch")
                return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=403)

        result = await process_webhook_payload(payload if isinstance(payload, dict) else {})
        return {"status": "ok", **result}

    @app.get("/whatsapp/status")
    async def whatsapp_status():
        from core.config import is_whatsapp_enabled
        from core.contact_link_store import list_links
        from core.whatsapp_templates import list_template_names
        from services.whatsapp_send_service import status_snapshot

        snap = status_snapshot()
        return {
            "status": "ok",
            "enabled": is_whatsapp_enabled(),
            "configured": bool(snap.get("configured")),
            "bsp": snap.get("bsp"),
            "link_count": len(list_links()),
            "templates": list_template_names(),
        }

    @app.post("/whatsapp/send-template")
    async def whatsapp_send_template(body: dict | None = None):
        from core.config import ACCOUNTS, is_whatsapp_enabled
        from services import whatsapp_send_service
        from services.crm_service import enrich_conversation

        if not is_whatsapp_enabled():
            return {"status": "error", "message": "WhatsApp is disabled"}

        payload = body or {}
        slot = str(payload.get("slot") or "").strip()
        if slot not in ACCOUNTS:
            return {"status": "error", "message": "Invalid slot"}

        user_id = payload.get("user_id")
        if user_id is None:
            return {"status": "error", "message": "user_id required"}

        template_key = str(
            payload.get("template") or payload.get("template_key") or ""
        ).strip()
        if not template_key:
            return {"status": "error", "message": "template required"}

        params = payload.get("params") or []
        if not isinstance(params, list):
            params = [str(params)]

        result = await whatsapp_send_service.send_template(
            slot,
            int(user_id),
            template_key,
            [str(p) for p in params],
            sent_by=str(payload.get("sent_by") or "manual"),
        )
        if not result.get("ok"):
            msg = result.get("error")
            if not msg and isinstance(result.get("response"), dict):
                msg = result["response"].get("message")
            return {
                "status": "error",
                "message": msg or "Template send failed",
            }

        summary = None
        if result.get("message"):
            from core.dm_store import load_inbox

            uid = int(user_id)
            stored = (load_inbox(slot).get("conversations") or {}).get(str(uid)) or {}
            summary = enrich_conversation(
                slot,
                {
                    "user_id": uid,
                    "username": stored.get("username") or "",
                    "name": stored.get("name") or "",
                    "last_message": stored.get("last_message") or "",
                    "last_message_at": stored.get("last_message_at"),
                    "unread_count": stored.get("unread_count") or 0,
                    "phone_e164": result.get("phone") or stored.get("phone_e164"),
                    "channels": stored.get("channels") or ["whatsapp"],
                },
            )

        return {
            "status": "ok",
            "message": result.get("message"),
            "phone": result.get("phone"),
            "template": template_key,
            "conversation": summary,
        }

    @app.get("/inbox/{slot}/wa-media/{user_id}/{message_id}")
    async def inbox_wa_media(slot: str, user_id: int, message_id: int):
        from fastapi import HTTPException
        from fastapi.responses import FileResponse

        from core.config import ACCOUNTS
        from core.dm_store import _find_message, load_inbox
        from core.wa_media_store import resolve_media_file
        from services.whatsapp_media_service import ensure_message_media_cached

        if slot not in ACCOUNTS:
            raise HTTPException(status_code=404, detail="Invalid slot")

        hit = resolve_media_file(slot, int(user_id), int(message_id))
        if not hit:
            conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id)))
            msg = _find_message(conv, int(message_id)) if conv else None
            wa_media_id = (msg or {}).get("wa_media_id") or (msg or {}).get("media_url")
            if wa_media_id:
                cached = await ensure_message_media_cached(
                    slot, int(user_id), int(message_id), str(wa_media_id),
                )
                if cached and cached.get("path"):
                    hit = (cached["path"], str(cached.get("mime") or "image/jpeg"))

        if not hit:
            raise HTTPException(status_code=404, detail="Media not found")
        path, mime = hit
        return FileResponse(path, media_type=mime)
