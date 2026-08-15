"""Interakt WhatsApp Business API client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import whatsapp_api_key
from core.phone_utils import normalize_phone

logger = logging.getLogger(__name__)

_INTERAKT_SEND_URL = "https://api.interakt.ai/v1/public/message/"


class InteraktClient:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (api_key or whatsapp_api_key()).strip()

    @property
    def configured(self) -> bool:
        return bool(self._api_key or whatsapp_api_key())

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Basic {self._api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _split_phone(phone_e164: str) -> tuple[str, str]:
        norm = normalize_phone(phone_e164) or phone_e164
        digits = "".join(ch for ch in norm if ch.isdigit())
        if digits.startswith("91") and len(digits) >= 12:
            return "+91", digits[2:]
        return "+91", digits[-10:] if len(digits) >= 10 else digits

    async def send_text(self, to_phone_e164: str, text: str) -> dict[str, Any]:
        api_key = self._api_key or whatsapp_api_key()
        if not api_key:
            return {"ok": False, "error": "WHATSAPP_API_KEY not set"}
        country_code, phone_number = self._split_phone(to_phone_e164)
        body = {
            "countryCode": country_code,
            "phoneNumber": phone_number,
            "type": "Text",
            "data": {"message": text},
        }
        headers = {
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(_INTERAKT_SEND_URL, json=body, headers=headers)
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                logger.warning("Interakt send failed %s: %s", resp.status_code, data)
                return {"ok": False, "status_code": resp.status_code, "response": data}
            return {"ok": True, "response": data}
        except Exception as exc:
            logger.warning("Interakt send error: %s", exc)
            return {"ok": False, "error": str(exc)}

    async def send_template(
        self,
        to_phone_e164: str,
        template_name: str,
        params: list[str],
        *,
        language_code: str = "en",
    ) -> dict[str, Any]:
        api_key = self._api_key or whatsapp_api_key()
        if not api_key:
            return {"ok": False, "error": "WHATSAPP_API_KEY not set"}
        country_code, phone_number = self._split_phone(to_phone_e164)
        body_values = [{"type": "text", "text": str(p)} for p in params]
        body = {
            "countryCode": country_code,
            "phoneNumber": phone_number,
            "type": "Template",
            "template": {
                "name": template_name,
                "languageCode": language_code,
                "bodyValues": [str(p) for p in params],
                "components": [
                    {
                        "type": "body",
                        "parameters": body_values,
                    }
                ],
            },
        }
        headers = {
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(_INTERAKT_SEND_URL, json=body, headers=headers)
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                logger.warning("Interakt template failed %s: %s", resp.status_code, data)
                return {"ok": False, "status_code": resp.status_code, "response": data}
            return {"ok": True, "response": data}
        except Exception as exc:
            logger.warning("Interakt template error: %s", exc)
            return {"ok": False, "error": str(exc)}
