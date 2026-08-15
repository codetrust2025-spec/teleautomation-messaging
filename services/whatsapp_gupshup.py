"""Gupshup WhatsApp Business API client (stub — wire when BSP account is ready)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import WHATSAPP_API_KEY, WHATSAPP_PHONE_NUMBER_ID
from core.phone_utils import normalize_phone

logger = logging.getLogger(__name__)


class GupshupClient:
    """Minimal Gupshup send wrapper. Extend when Gupshup is chosen as BSP."""

    def __init__(self, api_key: str | None = None, source: str | None = None) -> None:
        self._api_key = (api_key or WHATSAPP_API_KEY).strip()
        self._source = (source or WHATSAPP_PHONE_NUMBER_ID).strip()

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._source)

    async def send_text(self, to_phone_e164: str, text: str) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "WHATSAPP_API_KEY or WHATSAPP_PHONE_NUMBER_ID not set"}
        norm = normalize_phone(to_phone_e164) or to_phone_e164
        url = "https://api.gupshup.io/wa/api/v1/msg"
        headers = {"apikey": self._api_key, "Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "channel": "whatsapp",
            "source": self._source,
            "destination": norm,
            "message": text,
            "src.name": "TeleAutomation",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, data=payload, headers=headers)
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                return {"ok": False, "status_code": resp.status_code, "response": data}
            return {"ok": True, "response": data}
        except Exception as exc:
            logger.warning("Gupshup send error: %s", exc)
            return {"ok": False, "error": str(exc)}

    async def send_template(
        self,
        to_phone_e164: str,
        template_name: str,
        params: list[str],
        *,
        language_code: str = "en",
    ) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Gupshup not configured"}
        norm = normalize_phone(to_phone_e164) or to_phone_e164
        param_str = ",".join(str(p) for p in params)
        message = f"{template_name}|{language_code}|{param_str}"
        return await self.send_text(norm, message)
