"""Export a single inbox conversation to text, CSV, or JSON."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone

from core.dm_store import get_messages, load_inbox


def _conv_meta(slot: str, user_id: int) -> dict:
    data = load_inbox(slot) or {}
    conv = (data.get("conversations") or {}).get(str(user_id)) or {}
    return {
        "slot": slot,
        "user_id": int(user_id),
        "name": conv.get("name") or "",
        "username": conv.get("username") or "",
        "last_message_at": conv.get("last_message_at"),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


def _sender_label(message: dict, contact_name: str) -> str:
    if message.get("direction") == "in":
        return contact_name or "Contact"
    name = (message.get("sender_name") or "").strip()
    if name:
        return name
    sb = (message.get("sent_by") or "").strip().lower()
    if sb == "ai" or message.get("ai"):
        return "AI"
    if sb in ("native", "telegram", "telegram_app"):
        return name or "Telegram"
    if sb in ("manual", "ai_approved", "operator"):
        return "Operator"
    return "Team"


def _format_ts(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        from core.ist_time import _to_ist

        return _to_ist(d).strftime("%Y-%m-%d %H:%M IST")
    except (TypeError, ValueError):
        return str(iso)


def _safe_filename_part(value: str, fallback: str = "chat") -> str:
    s = re.sub(r"[^\w\-]+", "_", (value or "").strip(), flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:60] or fallback)


def build_export_filename(slot: str, user_id: int, meta: dict, ext: str) -> str:
    label = meta.get("name") or meta.get("username") or str(user_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{_safe_filename_part(label)}_{slot}_{user_id}_{stamp}.{ext}"


def export_conversation_text(slot: str, user_id: int) -> tuple[str, str]:
    meta = _conv_meta(slot, user_id)
    messages = get_messages(slot, user_id)
    contact = meta.get("name") or meta.get("username") or f"User {user_id}"
    lines = [
        "TeleAutomation — Chat export",
        f"Account: {slot}",
        f"Contact: {contact}",
    ]
    if meta.get("username"):
        lines.append(f"Username: @{meta['username'].lstrip('@')}")
    lines.append(f"User ID: {user_id}")
    lines.append(f"Exported: {_format_ts(meta.get('exported_at'))}")
    lines.append(f"Messages: {len(messages)}")
    lines.append("")
    for m in messages:
        if m.get("direction") == "system":
            lines.append(f"--- {m.get('text') or 'System'} ---")
            continue
        arrow = "←" if m.get("direction") == "in" else "→"
        sender = _sender_label(m, contact)
        ts = _format_ts(m.get("timestamp"))
        text = (m.get("text") or "").strip() or "[media]"
        if m.get("media_type"):
            text = f"[{m.get('media_type')}] {text}".strip()
        lines.append(f"[{ts}] {sender} {arrow} {text}")
    body = "\n".join(lines) + "\n"
    return body, build_export_filename(slot, user_id, meta, "txt")


def export_conversation_csv(slot: str, user_id: int) -> tuple[str, str]:
    meta = _conv_meta(slot, user_id)
    messages = get_messages(slot, user_id)
    contact = meta.get("name") or meta.get("username") or f"User {user_id}"
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "timestamp",
        "direction",
        "sender",
        "text",
        "media_type",
        "message_id",
        "status",
        "sent_by",
    ])
    for m in messages:
        writer.writerow([
            m.get("timestamp") or "",
            m.get("direction") or "",
            _sender_label(m, contact),
            m.get("text") or "",
            m.get("media_type") or "",
            m.get("id") or "",
            m.get("status") or "",
            m.get("sent_by") or "",
        ])
    return buf.getvalue(), build_export_filename(slot, user_id, meta, "csv")


def export_conversation_json(slot: str, user_id: int) -> tuple[str, str]:
    meta = _conv_meta(slot, user_id)
    messages = get_messages(slot, user_id)
    payload = {"conversation": meta, "messages": messages}
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return body, build_export_filename(slot, user_id, meta, "json")


def export_conversation(
    slot: str,
    user_id: int,
    fmt: str,
) -> tuple[bytes, str, str]:
    """Return (content_bytes, mime_type, filename)."""
    f = (fmt or "txt").strip().lower()
    if f == "csv":
        text, name = export_conversation_csv(slot, user_id)
        return text.encode("utf-8-sig"), "text/csv; charset=utf-8", name
    if f == "json":
        text, name = export_conversation_json(slot, user_id)
        return text.encode("utf-8"), "application/json; charset=utf-8", name
    text, name = export_conversation_text(slot, user_id)
    return text.encode("utf-8"), "text/plain; charset=utf-8", name
