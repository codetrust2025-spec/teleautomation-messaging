"""Normalize Indian mobile numbers for WhatsApp linking."""

from __future__ import annotations

import re

_IN_PHONE_RE = re.compile(r"(?:\+91|91)?[\s-]?([6-9]\d{9})")


def normalize_phone(value: str | None) -> str | None:
    """Return E.164-style digits without '+' (e.g. 919876543210) or None."""
    raw = (value or "").strip()
    if not raw:
        return None
    match = _IN_PHONE_RE.search(raw.replace(" ", ""))
    if not match:
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 10 and digits[0] in "6789":
            return f"91{digits}"
        if len(digits) == 12 and digits.startswith("91"):
            return digits
        return None
    return f"91{match.group(1)}"


def phone_display(e164: str | None) -> str:
    """Human-readable +91 format."""
    norm = normalize_phone(e164)
    if not norm or len(norm) < 12:
        return e164 or ""
    return f"+{norm[:2]} {norm[2:7]} {norm[7:]}"
