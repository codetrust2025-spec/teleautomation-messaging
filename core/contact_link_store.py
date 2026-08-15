"""Link WhatsApp phone numbers to Telegram CRM leads."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from threading import Lock

from core.config import DATA_DIR
from core.phone_utils import normalize_phone

_LINKS_FILE = os.path.join(DATA_DIR, "contact_links.json")
_lock = Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_all() -> dict[str, dict]:
    with _lock:
        if not os.path.exists(_LINKS_FILE):
            return {}
        try:
            with open(_LINKS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            links = data.get("links") or {}
            return dict(links) if isinstance(links, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}


def _save_all(links: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(_LINKS_FILE), exist_ok=True)
    payload = {"links": links, "updated_at": _now_iso()}
    with _lock:
        tmp = _LINKS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _LINKS_FILE)


def link_phone(
    account_slot: str,
    telegram_user_id: int,
    phone: str,
    *,
    linked_by: str = "auto",
    profile_name: str = "",
    whatsapp_wa_id: str = "",
) -> dict | None:
    """Create or update phone ↔ Telegram mapping. Returns link dict or None if phone invalid."""
    phone_e164 = normalize_phone(phone)
    if not phone_e164:
        return None
    link = {
        "phone_e164": phone_e164,
        "account_slot": account_slot,
        "telegram_user_id": int(telegram_user_id),
        "whatsapp_wa_id": whatsapp_wa_id or phone_e164,
        "profile_name": profile_name or "",
        "linked_at": _now_iso(),
        "linked_by": linked_by,
    }
    links = _load_all()
    links[phone_e164] = link
    _save_all(links)
    return link


def get_by_phone(phone: str) -> dict | None:
    phone_e164 = normalize_phone(phone)
    if not phone_e164:
        return None
    return _load_all().get(phone_e164)


def find_by_phone(phone: str) -> dict | None:
    """Alias for get_by_phone."""
    return get_by_phone(phone)


def get_by_telegram(account_slot: str, telegram_user_id: int) -> dict | None:
    uid = int(telegram_user_id)
    for link in _load_all().values():
        if link.get("account_slot") == account_slot and int(link.get("telegram_user_id") or 0) == uid:
            return dict(link)
    return None


def get_link(account_slot: str, telegram_user_id: int) -> dict | None:
    """Alias for get_by_telegram."""
    return get_by_telegram(account_slot, telegram_user_id)


def unlink_phone(phone: str) -> bool:
    phone_e164 = normalize_phone(phone)
    if not phone_e164:
        return False
    links = _load_all()
    if phone_e164 not in links:
        return False
    del links[phone_e164]
    _save_all(links)
    return True


def list_links() -> list[dict]:
    return list(_load_all().values())
