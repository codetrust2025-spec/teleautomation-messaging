"""Private endpoints used by the independently deployed Operations service."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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
        result = await _deliver_notification(body)
        if result["attempted"] and not (result["web_push_deliveries"] or result["whatsapp_deliveries"]) and result["errors"]:
            # Nothing went out and something failed. Answer 503 so Operations
            # keeps the notification pending and retries it (bounded, then
            # "dead", which ops_health reports) instead of recording a
            # delivery that never happened. Once any recipient has been reached
            # the claim is kept, so a retry never repeats an alert to anyone.
            release(idempotency_key)
            return JSONResponse({"status": "undelivered", **result}, status_code=503)
        return {"status": "ok", **result}


def _alert_phones() -> list[str]:
    return [item.strip() for item in os.getenv("WHATSAPP_SLOTS_NOTIFY_PHONES", "").split(",") if item.strip()]


def _template_param(text: str) -> str:
    # Meta rejects template variables with newlines, tabs or more than four
    # consecutive spaces, and caps a variable at 1024 characters.
    flat = " | ".join(line.strip() for line in text.splitlines() if line.strip())
    flat = " ".join(flat.split())
    return flat if len(flat) <= 1024 else flat[:1021] + "..."


async def _deliver_notification(body: "NotificationCommandV1") -> dict:
    """Send one notification to every configured recipient, once.

    Counts only sends the provider accepted. Each recipient is isolated, so one
    failure neither hides the others nor turns into a retry that repeats them.
    """
    from features import web_push

    out = {"web_push_deliveries": 0, "web_push_failures": 0, "whatsapp_deliveries": 0,
           "whatsapp_failures": 0, "whatsapp_mode": "", "attempted": 0, "errors": []}
    for username in web_push.all_usernames_with_subscriptions():
        out["attempted"] += 1
        try:
            ok = bool(web_push.send_to_user(username, title=body.title, body=body.body, tag=body.tag))
        except Exception as exc:  # noqa: BLE001
            ok = False
            out["errors"].append(f"push:{type(exc).__name__}")
        out["web_push_deliveries" if ok else "web_push_failures"] += 1

    whatsapp_text = body.whatsapp_text.strip()
    phones = _alert_phones()
    if not (whatsapp_text and phones):
        return out
    from services.whatsapp_bsp import get_bsp_client

    client = get_bsp_client()
    if client is None or not client.configured:
        out["errors"].append("whatsapp:not_configured")
        return out
    template = os.getenv("WHATSAPP_ALERT_TEMPLATE", "").strip()
    language = os.getenv("WHATSAPP_ALERT_TEMPLATE_LANG", "").strip() or "en"
    # Free text reaches a number only inside its 24-hour customer-service
    # window; an approved template reaches it at any time.
    out["whatsapp_mode"] = "template" if template else "text"
    for phone in phones:
        out["attempted"] += 1
        try:
            if template:
                result = await client.send_template(phone, template, [_template_param(whatsapp_text)],
                                                    language_code=language)
            else:
                result = await client.send_text(phone, whatsapp_text)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": type(exc).__name__}
        if isinstance(result, dict) and result.get("ok"):
            out["whatsapp_deliveries"] += 1
        else:
            out["whatsapp_failures"] += 1
            out["errors"].append("whatsapp:refused")
            logger.warning("notification WhatsApp %s to ...%s refused: %s", out["whatsapp_mode"], phone[-4:], result)
    return out
