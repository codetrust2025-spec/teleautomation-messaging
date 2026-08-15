"""Rule-based inbound spam classification (Karthik spam guard)."""

from __future__ import annotations

import re
from typing import Iterable

# Strong solicitation / scam signals (weight 4 each, cap once per pattern group)
_STRONG = [
    re.compile(r"body\s*massage", re.I),
    re.compile(r"\bnude\b", re.I),
    re.compile(r"\bescort\b", re.I),
    re.compile(r"call\s*girl", re.I),
    re.compile(r"sex\s+with", re.I),
    re.compile(r"incall|outcall", re.I),
    re.compile(r"booking\s+confirmation", re.I),
    re.compile(r"onlyfans|adult\s+service", re.I),
    re.compile(r"crypto\s+airdrop.*send", re.I),
    re.compile(r"double\s+your\s+(?:btc|usdt|money)", re.I),
]

_MEDIUM = [
    re.compile(r"24\s*[x×]\s*7", re.I),
    re.compile(r"\d+\s*hours?\s*[=:]\s*\d+\s*/\s*-", re.I),
    re.compile(r"full\s+(?:day|night)\s*[=:]", re.I),
    re.compile(r"genuine\s+trusted", re.I),
    re.compile(r"girls?\s+available", re.I),
    re.compile(r"customer\s+review", re.I),
    re.compile(r"refund.*(?:girl|money)", re.I),
    re.compile(r"privacy\s+compulsory", re.I),
    re.compile(r"earn\s+\$\d+.*per\s+(?:day|hour)", re.I),
    re.compile(r"work\s+from\s+home.*\d{3,}", re.I),
]

_WEAK = [
    re.compile(r"t\.me/\S+", re.I),
    re.compile(r"wa\.me/\d+", re.I),
    re.compile(r"₹\s*\d+|\d+\s*/\s*-", re.I),
    re.compile(r"verified\s+service", re.I),
]

# Telegram service account — login OTP codes, not real leads
_TELEGRAM_SERVICE_USER_IDS = frozenset({777000, 42777})


def is_telegram_service_chat(
    text: str,
    *,
    name: str = "",
    username: str = "",
    user_id: int = 0,
) -> bool:
    """Official Telegram / login-code threads — never Karthik leads."""
    if int(user_id) in _TELEGRAM_SERVICE_USER_IDS:
        return True
    blob = f"{name} {username} {(text or '')}".lower()
    if (name or "").strip().lower() == "telegram":
        if "login code" in blob:
            return True
    lower = (text or "").lower()
    if "login code:" in lower and "do not give this code" in lower:
        return True
    if "we never ask it for anything else" in lower and "login code" in lower:
        return True
    return False


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 40:
        return 0.0
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters)


def _price_hits(text: str) -> int:
    return len(re.findall(r"\d{3,5}\s*/\s*-|\d+\s*hours?\s*[=:]", text, re.I))


def classify_inbound_spam(
    text: str,
    *,
    name: str = "",
    username: str = "",
    user_id: int = 0,
    extra_texts: Iterable[str] | None = None,
) -> dict:
    """
    Returns { is_spam, confidence, reason, signals }.
    confidence 0–1 for UI; auto-block uses >= 0.72.
    """
    if is_telegram_service_chat(text, name=name, username=username, user_id=user_id):
        return {
            "is_spam": True,
            "confidence": 1.0,
            "reason": "telegram_system",
            "signals": ["telegram_login_code"],
        }

    chunks = [str(text or "").strip()]
    if extra_texts:
        chunks.extend(str(t or "").strip() for t in extra_texts if str(t or "").strip())
    combined = "\n".join(chunks).strip()
    if not combined:
        return {"is_spam": False, "confidence": 0.0, "reason": "", "signals": []}

    lower = combined.lower()
    signals: list[str] = []
    score = 0

    for rx in _STRONG:
        if rx.search(combined):
            signals.append(rx.pattern[:48])
            score += 4

    for rx in _MEDIUM:
        if rx.search(combined):
            signals.append(rx.pattern[:48])
            score += 2

    for rx in _WEAK:
        if rx.search(combined):
            signals.append(rx.pattern[:48])
            score += 1

    if _caps_ratio(combined) >= 0.55 and len(combined) >= 120:
        signals.append("heavy_caps")
        score += 2

    if _price_hits(combined) >= 3:
        signals.append("price_list")
        score += 2

    display = f"{name} {username}".lower()
    if "verified" in display and score >= 4:
        signals.append("spam_display_name")
        score += 2

    # Dedupe signals for display
    seen: set[str] = set()
    uniq: list[str] = []
    for s in signals:
        if s not in seen:
            seen.add(s)
            uniq.append(s)

    confidence = min(1.0, score / 12.0)
    is_spam = score >= 6 or (score >= 4 and len(combined) >= 180)

    reason = ""
    if is_spam:
        if any("massage" in s or "nude" in s or "escort" in s for s in uniq):
            reason = "solicitation_spam"
        elif "price_list" in uniq or "heavy_caps" in uniq:
            reason = "promo_spam"
        else:
            reason = "inbound_spam"

    return {
        "is_spam": is_spam,
        "confidence": round(confidence, 2),
        "reason": reason,
        "signals": uniq[:8],
    }
