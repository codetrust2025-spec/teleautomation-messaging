"""Private endpoints used by the independently deployed Operations service."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field


class NotificationCommandV1(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=4000)
    tag: str = Field(min_length=1, max_length=200)
    whatsapp_text: str = Field(default="", max_length=4000)


def _authorize(request: Request) -> None:
    expected = (os.getenv("INTERNAL_SERVICE_TOKEN") or "").strip()
    supplied = (request.headers.get("X-Internal-Service-Token") or "").strip()
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Invalid service credential")


def _parse_dt(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def install_internal_routes(app: FastAPI) -> None:
    @app.get("/internal/v1/operational-summary", include_in_schema=False)
    async def operational_summary(request: Request, stale_days: int = 2):
        """Return a bounded, read-only CRM projection for Operations reporting."""
        _authorize(request)
        from core.crm_store import CRM_INACTIVE_STATUSES, list_leads

        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(days=max(1, min(int(stale_days), 90)))
        followups: list[dict] = []
        stale: list[dict] = []
        for key, raw in list_leads().items():
            if str(raw.get("status") or "").lower() in CRM_INACTIVE_STATUSES:
                continue
            row = {
                "id": str(raw.get("user_id") or key),
                "name": str(raw.get("name") or raw.get("username") or "Unknown"),
            }
            reminder = _parse_dt(raw.get("reminder_timestamp"))
            if reminder and reminder <= now:
                followups.append(row)
            last_activity = _parse_dt(
                raw.get("last_reply_at") or raw.get("last_contact_time") or raw.get("created_at")
            )
            if last_activity and last_activity < stale_cutoff:
                stale.append(row)
        return {
            "status": "ok",
            "generated_at": now.isoformat(),
            "followups_due": followups,
            "stale_leads": stale,
        }

    @app.post("/internal/v1/notifications", include_in_schema=False)
    async def receive_notification(request: Request, body: NotificationCommandV1):
        _authorize(request)
        from features.service_inbox import claim, release
        idempotency_key = request.headers.get("X-Idempotency-Key") or ""
        if not idempotency_key:
            raise HTTPException(status_code=400, detail="X-Idempotency-Key is required")
        if not claim(idempotency_key):
            return {"status": "duplicate", "web_push_deliveries": 0, "whatsapp_deliveries": 0}
        try:
            from features import web_push
            delivered = 0
            for username in web_push.all_usernames_with_subscriptions():
                delivered += int(bool(web_push.send_to_user(username, title=body.title, body=body.body, tag=body.tag)))
            whatsapp_deliveries = 0
            whatsapp_text = body.whatsapp_text.strip()
            phones = [item.strip() for item in os.getenv("WHATSAPP_SLOTS_NOTIFY_PHONES", "").split(",") if item.strip()]
            if whatsapp_text and phones:
                from services.whatsapp_bsp import get_bsp_client
                client = get_bsp_client()
                if client is not None and client.configured:
                    for phone in phones:
                        await client.send_text(phone, whatsapp_text)
                        whatsapp_deliveries += 1
            return {"status": "ok", "web_push_deliveries": delivered, "whatsapp_deliveries": whatsapp_deliveries}
        except Exception:
            release(idempotency_key)
            raise
