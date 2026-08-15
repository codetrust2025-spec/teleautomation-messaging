"""Message text — read-only for workers; write only via API."""

import os

from core.config import DEFAULT_MESSAGE, MESSAGE_FILE, STATE_DIR


def _account_message_path(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, "message.txt")


def load_message() -> str:
    """Shared default message (read-only for workers)."""
    if os.path.exists(MESSAGE_FILE):
        try:
            with open(MESSAGE_FILE, "r", encoding="utf-8") as f:
                text = f.read().strip()
                if text:
                    return text
        except Exception:
            pass
    return DEFAULT_MESSAGE


def load_message_for_account(slot: str) -> str:
    """Per-account message only — never falls back to the fleet shared message."""
    path = _account_message_path(slot)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


def save_message(text: str) -> None:
    os.makedirs(os.path.dirname(MESSAGE_FILE), exist_ok=True)
    with open(MESSAGE_FILE, "w", encoding="utf-8") as f:
        f.write(text)


def save_message_for_account(slot: str, text: str) -> None:
    """Per-account message override — isolated from other accounts."""
    from core.config import ACCOUNTS

    if slot not in ACCOUNTS:
        raise ValueError(f"Invalid slot: {slot}")
    path = _account_message_path(slot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
