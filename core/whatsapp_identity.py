"""Stable synthetic Telegram-style user IDs for WhatsApp-only leads."""

from __future__ import annotations

import hashlib

from core.phone_utils import normalize_phone


# JavaScript Number.MAX_SAFE_INTEGER — WA synthetic IDs must stay within this range.
_JS_MAX_SAFE = 9007199254740991


def phone_to_synthetic_user_id(phone: str) -> int:
    """Negative bigint derived from phone — avoids collision with Telegram user IDs."""
    norm = normalize_phone(phone) or phone.strip()
    digest = hashlib.sha256(norm.encode("utf-8")).digest()
    num = int.from_bytes(digest[:7], "big") & _JS_MAX_SAFE
    return -int(num or 1)


def wa_message_id_to_int(wa_message_id: str) -> int:
    """Numeric inbox message id for dedup (distinct from Telegram message ids)."""
    digest = hashlib.sha256(wa_message_id.encode("utf-8")).digest()
    # Set high bit pattern so WA ids are unlikely to collide with Telegram ids.
    return int.from_bytes(digest[:6], "big") | (1 << 40)
