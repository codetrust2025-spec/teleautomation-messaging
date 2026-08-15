"""Karthik spam guard — detect and block solicitation / scam DMs."""

from __future__ import annotations

import logging
import os

from core.block_store import is_blocked
from core.config import ACCOUNTS
from core.spam_detector import classify_inbound_spam
from services.block_service import block_lead

logger = logging.getLogger(__name__)

AUTO_BLOCK_MIN_CONFIDENCE = float(os.environ.get("SPAM_AUTO_BLOCK_MIN_CONFIDENCE", "0.55"))


def _auto_block_enabled() -> bool:
    return os.environ.get("SPAM_AUTO_BLOCK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _inbound_texts_from_conv(conv: dict, *, max_msgs: int = 6) -> list[str]:
    texts: list[str] = []
    for m in reversed(conv.get("messages") or []):
        if m.get("direction") != "in":
            continue
        t = (m.get("text") or "").strip()
        if t:
            texts.append(t)
        if len(texts) >= max_msgs:
            break
    return texts


def classify_conversation_spam(slot: str, conv: dict) -> dict:
    uid = int(conv.get("user_id") or 0)
    if uid <= 0:
        return {"is_spam": False, "confidence": 0.0, "reason": "", "signals": []}
    texts = _inbound_texts_from_conv(conv)
    preview = (conv.get("last_message") or "").strip()
    if preview and preview not in texts:
        texts.insert(0, preview)
    if not texts:
        return {"is_spam": False, "confidence": 0.0, "reason": "", "signals": []}
    return classify_inbound_spam(
        texts[0],
        name=conv.get("name") or "",
        username=conv.get("username") or "",
        user_id=uid,
        extra_texts=texts[1:3],
    )


async def maybe_auto_block_inbound(
    slot: str,
    user_id: int,
    text: str,
    *,
    name: str = "",
    username: str = "",
) -> dict | None:
    """Block lead when inbound text matches spam rules. Returns block result or None."""
    if not _auto_block_enabled():
        return None
    if is_blocked(slot, int(user_id)):
        return None

    verdict = classify_inbound_spam(
        text, name=name, username=username, user_id=int(user_id),
    )
    if not verdict.get("is_spam"):
        return None
    if float(verdict.get("confidence") or 0) < AUTO_BLOCK_MIN_CONFIDENCE:
        return None

    result = await block_lead(slot, int(user_id), reason="spam")
    from services.crm_service import broadcast_crm_update

    await broadcast_crm_update(slot, int(user_id), result["lead"])
    logger.info(
        "Karthik spam guard blocked %s:%s (%s) signals=%s",
        slot,
        user_id,
        verdict.get("reason"),
        verdict.get("signals"),
    )
    return {
        "blocked": True,
        "lead": result["lead"],
        "entry": result.get("entry"),
        "verdict": verdict,
    }


async def block_chat_as_spam(slot: str, user_id: int) -> dict:
    """Operator/Karthik action — block current chat as spam."""
    if is_blocked(slot, int(user_id)):
        from core.crm_store import get_lead

        lead = get_lead(slot, int(user_id))
        return {"blocked": True, "already_blocked": True, "lead": lead, "verdict": {}}
    result = await block_lead(slot, int(user_id), reason="spam")
    from services.crm_service import broadcast_crm_update

    await broadcast_crm_update(slot, int(user_id), result["lead"])
    return {
        "blocked": True,
        "lead": result["lead"],
        "entry": result.get("entry"),
    }


async def scan_inbox_and_block_spam(*, slot: str | None = None) -> dict:
    """Scan stored conversations and block obvious spam threads."""
    from core.dm_store import load_inbox
    from services.crm_service import broadcast_crm_update

    slots = [slot] if slot else list(ACCOUNTS)
    blocked_rows: list[dict] = []
    scanned = 0

    for s in slots:
        if s not in ACCOUNTS:
            continue
        data = load_inbox(s)
        for conv in (data.get("conversations") or {}).values():
            uid = int(conv.get("user_id") or 0)
            if uid <= 0:
                continue
            scanned += 1
            if is_blocked(s, uid):
                continue
            verdict = classify_conversation_spam(s, conv)
            if not verdict.get("is_spam"):
                continue
            if float(verdict.get("confidence") or 0) < AUTO_BLOCK_MIN_CONFIDENCE:
                continue
            result = await block_lead(s, uid, reason="spam")
            await broadcast_crm_update(s, uid, result["lead"])
            blocked_rows.append(
                {
                    "slot": s,
                    "user_id": uid,
                    "name": conv.get("name") or "",
                    "username": conv.get("username") or "",
                    "reason": verdict.get("reason") or "spam",
                    "confidence": verdict.get("confidence"),
                    "signals": verdict.get("signals") or [],
                }
            )
            logger.info(
                "Karthik scan blocked %s:%s confidence=%s",
                s,
                uid,
                verdict.get("confidence"),
            )

    return {
        "scanned": scanned,
        "blocked_count": len(blocked_rows),
        "blocked": blocked_rows,
    }
