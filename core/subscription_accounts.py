"""Detect and configure subscription (channel-focused) account slots."""

from __future__ import annotations

import json
import os
from threading import Lock

from core.config import DATA_DIR

_SUBSCRIPTION_FILE = os.path.join(DATA_DIR, "subscription_accounts.json")
_lock = Lock()

def _empty() -> dict:
    return {"slots": [], "notes": ""}


def load_manual_subscription_slots() -> list[str]:
    with _lock:
        if not os.path.exists(_SUBSCRIPTION_FILE):
            return []
        try:
            with open(_SUBSCRIPTION_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return []
            raw = data.get("slots") or []
            return [str(s).strip() for s in raw if str(s).strip()]
        except (json.JSONDecodeError, OSError):
            return []


def load_subscription_slots() -> list[str]:
    """Manual list only (backward compatible)."""
    return load_manual_subscription_slots()


def classify_account_info(info: dict | None) -> bool:
    """
    Subscription account = explicitly configured, not guessed.

    True only when:
    - Slot is listed in data/subscription_accounts.json, OR
    - Telegram reports Premium on this user (factual API flag).
    """
    if not info or not info.get("phone"):
        return False

    slot = str(info.get("slot") or "").strip()
    if slot and slot in load_manual_subscription_slots():
        return True

    if info.get("telegram_premium") is True:
        return True

    return False


def enrich_account_info(slot: str, info: dict) -> dict:
    """Add is_subscription flag from manual list or Telegram Premium."""
    if not info:
        return info
    out = dict(info)
    out["slot"] = slot
    out["is_subscription"] = classify_account_info(out)
    return out


def compute_subscription_slots(account_info_by_slot: dict[str, dict | None]) -> list[str]:
    """All slots that qualify as subscription accounts right now."""
    manual = set(load_manual_subscription_slots())
    detected: list[str] = []
    for slot, info in (account_info_by_slot or {}).items():
        if not info:
            continue
        merged = enrich_account_info(slot, info)
        if merged.get("is_subscription"):
            detected.append(slot)
    return sorted(set(detected) | manual)


def save_subscription_slots(slots: list[str], *, notes: str = "") -> None:
    with _lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        payload = {"slots": list(slots), "notes": notes or ""}
        tmp = _SUBSCRIPTION_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _SUBSCRIPTION_FILE)


def is_subscription_slot(slot: str) -> bool:
    return slot in load_manual_subscription_slots()
