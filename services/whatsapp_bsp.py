"""WhatsApp BSP abstraction — parse webhooks and send messages."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any

from core.config import WHATSAPP_WEBHOOK_VERIFY_TOKEN, whatsapp_webhook_verify_token

logger = logging.getLogger(__name__)


@dataclass
class InboundWaMessage:
    from_phone_e164: str
    wa_message_id: str
    text: str
    timestamp: str | None
    profile_name: str
    message_type: str = "text"
    media_url: str | None = None
    media_mime: str | None = None


@dataclass
class WaStatusUpdate:
    wa_message_id: str
    status: str
    recipient_phone_e164: str | None = None


def verify_webhook_challenge(
    mode: str | None,
    token: str | None,
    challenge: str | None,
) -> str | None:
    """Meta/Interakt GET verification — return challenge string or None."""
    if not challenge:
        return None
    if mode and str(mode).strip().lower() not in ("subscribe", "subscription"):
        return None
    import os

    expected = (whatsapp_webhook_verify_token() or WHATSAPP_WEBHOOK_VERIFY_TOKEN).strip()
    if not expected:
        logger.warning("WHATSAPP_WEBHOOK_VERIFY_TOKEN not set — rejecting verify")
        return None
    if (token or "").strip() != expected:
        logger.warning("WhatsApp webhook verify token mismatch")
        return None
    return str(challenge)


def verify_interakt_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """Validate Interakt-Signature header (sha256= HMAC of raw body)."""
    if not secret:
        return False
    if not signature_header:
        return False
    sig = signature_header.strip()
    if sig.startswith("sha256="):
        sig = sig[7:]
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


def verify_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Validate X-Hub-Signature-256 when app secret is configured."""
    if not app_secret or not signature_header:
        return not app_secret
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


def _digits_only(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _normalize_from_raw(raw: str) -> str:
    digits = _digits_only(raw)
    if len(digits) == 10 and digits[0] in "6789":
        return f"91{digits}"
    return digits


def _parse_meta_cloud(payload: dict) -> tuple[list[InboundWaMessage], list[WaStatusUpdate]]:
    inbound: list[InboundWaMessage] = []
    statuses: list[WaStatusUpdate] = []
    if payload.get("object") != "whatsapp_business_account":
        return inbound, statuses
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            contacts = {
                _normalize_from_raw(c.get("wa_id", "")): (
                    (c.get("profile") or {}).get("name") or ""
                )
                for c in (value.get("contacts") or [])
            }
            for msg in value.get("messages") or []:
                from_phone = _normalize_from_raw(str(msg.get("from") or ""))
                if not from_phone:
                    continue
                msg_type = str(msg.get("type") or "text")
                text = ""
                media_url = None
                media_mime = None
                if msg_type == "text":
                    text = str((msg.get("text") or {}).get("body") or "")
                elif msg_type in ("image", "document", "video", "audio"):
                    media = msg.get(msg_type) or {}
                    media_url = media.get("id") or media.get("link")
                    media_mime = media.get("mime_type")
                    text = str(media.get("caption") or f"[{msg_type}]")
                else:
                    text = f"[{msg_type}]"
                inbound.append(
                    InboundWaMessage(
                        from_phone_e164=from_phone,
                        wa_message_id=str(msg.get("id") or ""),
                        text=text,
                        timestamp=str(msg.get("timestamp") or "") or None,
                        profile_name=contacts.get(from_phone, ""),
                        message_type=msg_type,
                        media_url=str(media_url) if media_url else None,
                        media_mime=media_mime,
                    )
                )
            for st in value.get("statuses") or []:
                statuses.append(
                    WaStatusUpdate(
                        wa_message_id=str(st.get("id") or ""),
                        status=str(st.get("status") or ""),
                        recipient_phone_e164=_normalize_from_raw(str(st.get("recipient_id") or "")) or None,
                    )
                )
    return inbound, statuses


def _parse_interakt(payload: dict) -> tuple[list[InboundWaMessage], list[WaStatusUpdate]]:
    inbound: list[InboundWaMessage] = []
    statuses: list[WaStatusUpdate] = []
    event_type = str(payload.get("type") or "").lower()
    data = payload.get("data") or {}

    if event_type in ("message_received", "message", "incoming_message"):
        customer = data.get("customer") or data.get("contact") or {}
        message = data.get("message") or data
        phone_raw = (
            customer.get("channel_phone_number")
            or customer.get("phone_number")
            or customer.get("phone")
            or message.get("from")
            or ""
        )
        from_phone = _normalize_from_raw(str(phone_raw))
        if not from_phone:
            logger.warning("Interakt webhook missing phone: keys=%s", list(customer.keys()))
            return inbound, statuses
        msg_type = str(
            message.get("message_type")
            or message.get("message_content_type")
            or message.get("type")
            or "text"
        ).lower()
        text = str(
            message.get("message")
            or message.get("text")
            or message.get("body")
            or ""
        )
        media_url = str(message.get("media_url") or "") or None
        if msg_type in ("image", "document", "video", "audio", "sticker"):
            if not text:
                text = f"[{msg_type}]"
        elif not text and msg_type != "text":
            text = f"[{msg_type}]"
        traits = customer.get("traits") or {}
        profile_name = str(
            customer.get("name")
            or traits.get("name")
            or traits.get("Name")
            or ""
        )
        inbound.append(
            InboundWaMessage(
                from_phone_e164=from_phone,
                wa_message_id=str(message.get("id") or message.get("message_id") or ""),
                text=text,
                timestamp=str(
                    message.get("received_at_utc")
                    or message.get("timestamp")
                    or payload.get("timestamp")
                    or ""
                ) or None,
                profile_name=profile_name,
                message_type=msg_type,
                media_url=media_url,
                media_mime=str(message.get("media_mime_type") or message.get("mime_type") or "") or None,
            )
        )
        return inbound, statuses

    if event_type in (
        "message_status",
        "message_status_update",
        "status",
        "message_api_sent",
        "message_api_delivered",
        "message_api_read",
        "message_api_failed",
        "message_api_clicked",
    ):
        message = data.get("message") or data
        statuses.append(
            WaStatusUpdate(
                wa_message_id=str(message.get("id") or message.get("message_id") or ""),
                status=str(message.get("status") or data.get("status") or ""),
                recipient_phone_e164=_normalize_from_raw(
                    str((data.get("customer") or {}).get("phone_number") or "")
                ) or None,
            )
        )
    return inbound, statuses


def parse_webhook_payload(payload: dict) -> tuple[list[InboundWaMessage], list[WaStatusUpdate]]:
    """Accept Meta Cloud API or Interakt-style webhook JSON."""
    if not isinstance(payload, dict):
        return [], []
    if payload.get("object") == "whatsapp_business_account":
        return _parse_meta_cloud(payload)
    if payload.get("type"):
        return _parse_interakt(payload)
    # Meta-style nested under entry without object (some BSP proxies)
    if payload.get("entry"):
        return _parse_meta_cloud({"object": "whatsapp_business_account", **payload})
    return [], []


def get_bsp_client():
    """Return configured BSP send client."""
    from core.config import _refresh_whatsapp_env_from_file, is_whatsapp_enabled, whatsapp_bsp_name

    _refresh_whatsapp_env_from_file()
    if not is_whatsapp_enabled():
        return None
    if whatsapp_bsp_name() == "gupshup":
        from services.whatsapp_gupshup import GupshupClient

        return GupshupClient()
    from services.whatsapp_interakt import InteraktClient

    return InteraktClient()
