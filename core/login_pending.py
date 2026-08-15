"""Persist OTP login state per account — survives server auto-reload."""

import json
import os

from core.config import ACCOUNTS, STATE_DIR


def _path(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, "login_pending.json")


def save_pending(
    slot: str,
    phone: str,
    phone_code_hash: str,
    *,
    session_string: str | None = None,
) -> None:
    if slot not in ACCOUNTS:
        raise ValueError(f"Invalid slot: {slot}")
    os.makedirs(os.path.dirname(_path(slot)), exist_ok=True)
    payload: dict = {"phone": phone, "phone_code_hash": str(phone_code_hash)}
    if session_string:
        payload["session_string"] = str(session_string)
    with open(_path(slot), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_pending(slot: str) -> dict | None:
    if slot not in ACCOUNTS:
        return None
    path = _path(slot)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("phone") and data.get("phone_code_hash"):
            return data
    except Exception:
        pass
    return None


def clear_pending(slot: str) -> None:
    path = _path(slot)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
