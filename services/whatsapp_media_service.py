"""Download WhatsApp media from Meta Cloud API / BSP."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from core.config import WHATSAPP_API_KEY, WHATSAPP_PHONE_NUMBER_ID
from core.wa_media_store import media_exists, save_media

logger = logging.getLogger(__name__)

_MIME_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _media_access_token() -> str:
    return (
        os.environ.get("WHATSAPP_MEDIA_ACCESS_TOKEN")
        or os.environ.get("WHATSAPP_META_ACCESS_TOKEN")
        or WHATSAPP_API_KEY
        or ""
    ).strip()


def _ext_from_mime(mime: str | None) -> str:
    if not mime:
        return "jpg"
    return _MIME_EXT.get(mime.lower().split(";")[0].strip(), "jpg")


async def download_wa_media(media_id: str) -> tuple[bytes, str] | None:
    """Fetch media bytes + mime type from Meta Graph API or direct URL (Interakt)."""
    if not media_id:
        return None
    media_ref = media_id.strip()
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            # Interakt / BSP often sends a full HTTPS URL in media_url.
            if media_ref.startswith("http://") or media_ref.startswith("https://"):
                file_resp = await client.get(media_ref)
                if file_resp.status_code >= 400:
                    logger.warning("WA direct media download %s: %s", file_resp.status_code, media_ref[:120])
                    return None
                mime = str(file_resp.headers.get("content-type") or "image/jpeg").split(";")[0]
                return file_resp.content, mime

            token = _media_access_token()
            if not token:
                logger.warning("WA media: no access token for Meta media id %s", media_ref[:40])
                return None
            graph_base = os.environ.get("WHATSAPP_GRAPH_URL", "https://graph.facebook.com/v21.0").rstrip("/")
            headers = {"Authorization": f"Bearer {token}"}
            params: dict[str, str] = {}
            if WHATSAPP_PHONE_NUMBER_ID:
                params["phone_number_id"] = WHATSAPP_PHONE_NUMBER_ID
            meta_resp = await client.get(f"{graph_base}/{media_ref}", headers=headers, params=params)
            if meta_resp.status_code >= 400:
                logger.warning("WA media meta %s: %s", meta_resp.status_code, meta_resp.text[:200])
                return None
            meta = meta_resp.json() if meta_resp.content else {}
            url = meta.get("url")
            mime = str(meta.get("mime_type") or "image/jpeg")
            if not url:
                return None
            file_resp = await client.get(url, headers=headers)
            if file_resp.status_code >= 400:
                logger.warning("WA media download %s", file_resp.status_code)
                return None
            return file_resp.content, mime
    except Exception as exc:
        logger.warning("WA media fetch error: %s", exc)
        return None


async def ensure_message_media_cached(
    slot: str,
    user_id: int,
    message_id: int,
    wa_media_id: str,
) -> dict[str, Any] | None:
    """Download if missing; return {path, mime, url} or None."""
    existing = media_exists(slot, user_id, message_id)
    if existing:
        from core.wa_media_store import public_media_url

        ext = existing.rsplit(".", 1)[-1].lower()
        return {
            "path": existing,
            "mime": f"image/{ext}",
            "url": public_media_url(slot, user_id, message_id),
            "cached": True,
        }
    fetched = await download_wa_media(wa_media_id)
    if not fetched:
        return None
    data, mime = fetched
    ext = _ext_from_mime(mime)
    path = save_media(slot, user_id, message_id, data, ext=ext)
    from core.wa_media_store import public_media_url

    return {
        "path": path,
        "mime": mime,
        "url": public_media_url(slot, user_id, message_id),
        "cached": False,
        "size": len(data),
    }


def maybe_save_payment_proof_from_wa(
    slot: str,
    user_id: int,
    data: bytes,
    mime: str,
    *,
    note: str = "WhatsApp inbound image",
) -> dict | None:
    """Forward a converted lead's payment proof to the Operations contract."""
    from core.crm_store import get_lead

    lead = get_lead(slot, int(user_id)) or {}
    cid = lead.get("candidate_id") or (lead.get("graph") or {}).get("candidate_id")
    if not cid:
        return None
    token = (os.environ.get("INTERNAL_SERVICE_TOKEN") or "").strip()
    if not token:
        logger.warning("WA proof forwarding skipped: internal service token is not configured")
        return None
    try:
        import hashlib
        import httpx

        ext = _ext_from_mime(mime)
        base = os.getenv("OPERATIONS_INTERNAL_URL", "http://127.0.0.1:8001").rstrip("/")
        digest = hashlib.sha256(data).hexdigest()
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{base}/internal/v1/candidates/{cid}/payment-proofs",
                headers={
                    "X-Internal-Service-Token": token,
                    "X-Idempotency-Key": f"wa-proof:{cid}:{digest}",
                },
                data={
                    "note": note[:200],
                    "source_module": "whatsapp_payment",
                    "upload_context": f"{slot}:{int(user_id)}",
                },
                files={"file": (f"whatsapp_{int(user_id)}.{ext}", data, mime)},
            )
            response.raise_for_status()
            entry = response.json().get("payment_proof")
        logger.info("WA image forwarded as candidate proof for lead %s:%s", slot, user_id)
        return entry
    except Exception as exc:
        logger.warning("WA proof attach failed %s:%s: %s", slot, user_id, exc)
        return None
