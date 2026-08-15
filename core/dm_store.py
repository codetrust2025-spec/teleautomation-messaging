"""Persist private DM conversations per account slot — never group/channel data."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from threading import Lock

from core.config import ACCOUNT_SLOTS, STATE_DIR


def slot_telegram_account_display(slot: str) -> str:
    """Display name for messages sent from the native Telegram app (not the dashboard)."""
    try:
        from core.account_info_store import load_account_info

        info = load_account_info(slot) or {}
        name = (info.get("name") or info.get("first_name") or "").strip()
        if name:
            return name
    except Exception:
        pass
    return "Telegram"

_MAX_MESSAGES_PER_CHAT = 300
_file_locks: dict[str, Lock] = {}

# Outbound: sending (UI-only) → sent → delivered → read | failed
# Inbound: received → read (when agent marks conversation read)
_OUTBOUND_RANK = {
    "failed": 0,
    "sending": 1,
    "sent": 2,
    "delivered": 3,
    "read": 4,
}


def _path(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, "dm_inbox.json")


def _lock(slot: str) -> Lock:
    if slot not in _file_locks:
        _file_locks[slot] = Lock()
    return _file_locks[slot]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict:
    return {"conversations": {}, "updated_at": _now_iso()}


def _can_advance_outbound(current: str, target: str) -> bool:
    if target == "failed":
        return current in ("sending", "sent")
    return _OUTBOUND_RANK.get(target, 0) > _OUTBOUND_RANK.get(current, 0)


def _normalize_outbound_record(m: dict) -> dict:
    """Upgrade legacy stored 'sent' to 'delivered' for display consistency."""
    if m.get("direction") != "out":
        return m
    out = dict(m)
    st = out.get("status") or "sent"
    if st == "sent":
        out["status"] = "delivered"
    return out


def load_inbox(slot: str) -> dict:
    path = _path(slot)
    with _lock(slot):
        if not os.path.exists(path):
            return _empty()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _empty()
            data.setdefault("conversations", {})
            return data
        except (json.JSONDecodeError, OSError):
            return _empty()


def save_inbox(slot: str, data: dict) -> None:
    path = _path(slot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["updated_at"] = _now_iso()
    with _lock(slot):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def _trim_messages(messages: list) -> list:
    if len(messages) <= _MAX_MESSAGES_PER_CHAT:
        return messages
    return messages[-_MAX_MESSAGES_PER_CHAT:]


def _find_message(conv: dict, message_id: int) -> dict | None:
    mid = int(message_id)
    for m in conv.get("messages") or []:
        if int(m.get("id") or 0) == mid:
            return m
    return None


def _sender_display_name(sent_by: str | None, *, operator_name: str | None = None) -> str | None:
    """Human-readable outbound sender for inbox UI."""
    sb = (sent_by or "").strip().lower()
    if sb == "ai":
        return "AI"
    if sb in ("native", "telegram", "telegram_app"):
        name = (operator_name or "").strip()
        return name if name else "Telegram"
    if sb in ("manual", "ai_approved", "operator"):
        name = (operator_name or "").strip()
        if name and name.lower() != "dev":
            return name if name[0].isupper() else name.capitalize()
        return "Operator"
    return None


def _apply_outbound_meta(
    record: dict,
    *,
    sent_by: str | None = None,
    sender_name: str | None = None,
    ai: bool = False,
    ai_stage: str | None = None,
    ai_confidence: float | None = None,
) -> dict:
    if record.get("direction") != "out":
        return record
    sb = (sent_by or "").strip().lower()
    if sb:
        record["sent_by"] = sb
    if sb in ("native", "telegram", "telegram_app"):
        record.pop("ai", None)
        record.pop("ai_stage", None)
        record.pop("ai_confidence", None)
    elif ai or sb == "ai":
        record["ai"] = True
    if ai_stage:
        record["ai_stage"] = ai_stage
    if ai_confidence is not None:
        try:
            record["ai_confidence"] = round(float(ai_confidence), 3)
        except (TypeError, ValueError):
            pass
    display = (sender_name or "").strip() or _sender_display_name(sb, operator_name=None)
    if not display and sb:
        display = _sender_display_name(sb)
    if display:
        record["sender_name"] = display
    return record


def classify_outbound_sender_repair(
    record: dict,
    *,
    account_display: str | None = None,
) -> tuple[str, str, bool] | None:
    """Infer correct AI vs human labels for stored outbound rows.

    Returns ``(sent_by, sender_name, ai)`` when the record should be updated,
    or ``None`` if it is already correct.

    Dashboard sends carry ``sent_by`` manual/ai_approved + handler name.
    Native Telegram app sends use ``sent_by`` native + account display name.
    Karthik auto-replies use ``sent_by`` ai + ``ai_stage``.
    """
    if record.get("direction") != "out":
        return None
    sb = (record.get("sent_by") or "").strip().lower()
    name = (record.get("sender_name") or "").strip()
    native_name = (account_display or "Telegram").strip() or "Telegram"

    if sb in ("native", "telegram", "telegram_app"):
        return None if name and name != "AI" else ("native", native_name, False)

    if sb in ("manual", "ai_approved") and name and name not in ("Operator", "AI"):
        return None

    if record.get("ai_stage") or record.get("ai_confidence") is not None:
        if sb == "ai" and name == "AI":
            return None
        return ("ai", "AI", True)

    if sb == "ai":
        if record.get("ai_stage") or record.get("ai_confidence") is not None:
            return None if name == "AI" else ("ai", "AI", True)
        # Mis-tagged native/tool send — no Karthik metadata
        return ("native", native_name, False)

    if sb in ("manual", "operator", "ai_approved"):
        return None

    # Legacy rows: no sent_by — treat as native app, never assume AI
    if not sb:
        return ("native", native_name, False)

    return None


def repair_outbound_sender_labels(slot: str) -> int:
    """Re-tag mislabeled outbound messages for one account slot. Returns patch count."""
    data = load_inbox(slot) or {}
    account_display = slot_telegram_account_display(slot)
    changed = False
    n = 0
    for conv in (data.get("conversations") or {}).values():
        for m in conv.get("messages") or []:
            fix = classify_outbound_sender_repair(m, account_display=account_display)
            if not fix:
                continue
            sent_by, sender_name, ai_flag = fix
            _apply_outbound_meta(m, sent_by=sent_by, sender_name=sender_name, ai=ai_flag)
            n += 1
            changed = True
    if changed:
        save_inbox(slot, data)
    return n


def append_message(
    slot: str,
    *,
    user_id: int,
    username: str,
    name: str,
    text: str,
    direction: str,
    telegram_id: int | None = None,
    status: str = "received",
    increment_unread: bool = False,
    account_id: str | None = None,
    timestamp: str | None = None,
    media: bool = False,
    media_type: str | None = None,
    sent_by: str | None = None,
    sender_name: str | None = None,
    ai: bool = False,
    ai_stage: str | None = None,
    ai_confidence: float | None = None,
    extra: dict | None = None,
) -> tuple[dict, dict, bool]:
    """Returns (conversation_summary, message_record, created). created=False if duplicate telegram_id."""
    data = load_inbox(slot)
    key = str(user_id)
    conv = data["conversations"].get(key) or {
        "user_id": user_id,
        "username": username,
        "name": name,
        "unread_count": 0,
        "last_message": "",
        "last_message_at": None,
        "messages": [],
    }
    conv["username"] = username or conv.get("username") or ""
    conv["name"] = name or conv.get("name") or str(user_id)

    msg_id = telegram_id or int(datetime.now(timezone.utc).timestamp() * 1000)
    record = {
        "id": msg_id,
        "chat_id": int(user_id),
        "account_id": account_id or slot,
        "direction": direction,
        "text": text or "",
        "timestamp": timestamp or _now_iso(),
        "status": status,
        "read_at": None,
    }
    if media or media_type:
        record["media"] = True
        if media_type:
            record["media_type"] = media_type
    if direction == "out":
        out_sent_by = sent_by
        out_sender = sender_name
        out_ai = ai
        if not out_sent_by and not out_ai and not ai_stage:
            out_sent_by = "native"
            out_sender = out_sender or slot_telegram_account_display(slot)
            out_ai = False
        _apply_outbound_meta(
            record,
            sent_by=out_sent_by,
            sender_name=out_sender,
            ai=out_ai,
            ai_stage=ai_stage,
            ai_confidence=ai_confidence,
        )

    if extra:
        for extra_key, val in extra.items():
            if val is not None:
                record[extra_key] = val
        phone = extra.get("phone_e164")
        if phone:
            conv["phone_e164"] = str(phone)
        channel = (extra.get("channel") or "").strip().lower()
        channels = set(conv.get("channels") or [])
        if channel in ("whatsapp", "telegram"):
            channels.add(channel)
        elif phone:
            channels.add("whatsapp")
        if channels:
            conv["channels"] = sorted(channels)

    msgs = conv.get("messages") or []
    if telegram_id and any(m.get("id") == telegram_id for m in msgs):
        existing = next(m for m in msgs if m.get("id") == telegram_id)
        updated = False
        if (media or media_type) and not existing.get("media_type"):
            existing["media"] = True
            if media_type:
                existing["media_type"] = media_type
            if not (existing.get("text") or "").strip() and (text or "").strip():
                existing["text"] = text
            updated = True
        if direction == "out":
            if sent_by or ai or ai_stage:
                _apply_outbound_meta(
                    existing,
                    sent_by=sent_by,
                    sender_name=sender_name,
                    ai=ai,
                    ai_stage=ai_stage,
                    ai_confidence=ai_confidence,
                )
                updated = True
            else:
                fix = classify_outbound_sender_repair(
                    existing, account_display=slot_telegram_account_display(slot),
                )
                if fix:
                    _apply_outbound_meta(
                        existing,
                        sent_by=fix[0],
                        sender_name=fix[1],
                        ai=fix[2],
                    )
                    updated = True
        if updated:
            conv["messages"] = msgs
            data["conversations"][key] = conv
            save_inbox(slot, data)
        return conv, _normalize_outbound_record(existing), False

    msgs.append(record)
    conv["messages"] = _trim_messages(msgs)
    conv["last_message"] = (text or "")[:500]
    prev_at = conv.get("last_message_at") or ""
    if not prev_at or (record["timestamp"] or "") >= prev_at:
        conv["last_message_at"] = record["timestamp"]

    if direction == "in" and increment_unread:
        conv["unread_count"] = int(conv.get("unread_count") or 0) + 1
    elif direction == "out":
        # Our reply — never show as unread in the sidebar
        conv["unread_count"] = 0

    data["conversations"][key] = conv
    save_inbox(slot, data)
    return conv, record, True


def patch_message(
    slot: str,
    user_id: int,
    message_id: int,
    fields: dict,
) -> dict | None:
    """Patch arbitrary fields on one message. Returns updated record or None."""
    if not fields:
        return None
    data = load_inbox(slot)
    key = str(int(user_id))
    conv = data.get("conversations", {}).get(key)
    if not conv:
        return None
    msg = _find_message(conv, int(message_id))
    if not msg:
        return None
    for k, v in fields.items():
        if v is not None:
            msg[k] = v
    data["conversations"][key] = conv
    save_inbox(slot, data)
    out = _normalize_outbound_record(msg) if msg.get("direction") == "out" else dict(msg)
    return out


def find_message_by_wa_id_any_slot(wa_id: str) -> tuple[str, int, dict] | None:
    """Scan all slots for an outbound/inbound row with matching wa_message_id."""
    needle = str(wa_id or "").strip()
    if not needle:
        return None
    for slot in ACCOUNT_SLOTS:
        data = load_inbox(slot)
        for key, conv in (data.get("conversations") or {}).items():
            for m in conv.get("messages") or []:
                if str(m.get("wa_message_id") or "") == needle:
                    try:
                        uid = int(key)
                    except (TypeError, ValueError):
                        uid = int(m.get("chat_id") or 0)
                    return slot, uid, m
    return None


def patch_message_text(
    slot: str,
    user_id: int,
    message_id: int,
    text: str,
    *,
    edited: bool = True,
) -> tuple[dict | None, dict | None]:
    """Update stored text for a message. Returns (conversation, message) or (None, None)."""
    data = load_inbox(slot)
    key = str(int(user_id))
    conv = data.get("conversations", {}).get(key)
    if not conv:
        return None, None
    msg = _find_message(conv, int(message_id))
    if not msg:
        return None, None
    clean = (text or "").strip()
    if not clean:
        return None, None
    msg["text"] = clean
    if edited:
        msg["edited"] = True
        msg["edited_at"] = _now_iso()
    msgs = conv.get("messages") or []
    if msgs and int(msgs[-1].get("id") or 0) == int(message_id):
        conv["last_message"] = clean[:500]
    data["conversations"][key] = conv
    save_inbox(slot, data)
    return conv, _normalize_outbound_record(msg) if msg.get("direction") == "out" else dict(msg)


def remove_message(slot: str, user_id: int, message_id: int) -> tuple[dict | None, dict | None]:
    """Remove one message from storage. Returns (conversation, removed_record)."""
    data = load_inbox(slot)
    key = str(int(user_id))
    conv = data.get("conversations", {}).get(key)
    if not conv:
        return None, None
    mid = int(message_id)
    msgs = list(conv.get("messages") or [])
    removed = None
    kept: list[dict] = []
    for m in msgs:
        if int(m.get("id") or 0) == mid:
            removed = m
        else:
            kept.append(m)
    if removed is None:
        return None, None
    conv["messages"] = kept
    if kept:
        last = kept[-1]
        conv["last_message"] = (last.get("text") or "")[:500]
        conv["last_message_at"] = last.get("timestamp") or conv.get("last_message_at")
    else:
        conv["last_message"] = ""
        conv["last_message_at"] = None
    data["conversations"][key] = conv
    save_inbox(slot, data)
    return conv, removed


def update_outbound_status(
    slot: str,
    user_id: int,
    message_id: int,
    status: str,
    *,
    read_at: str | None = None,
) -> dict | None:
    """Advance a single outbound message status. Returns updated record or None."""
    data = load_inbox(slot)
    key = str(user_id)
    conv = data.get("conversations", {}).get(key)
    if not conv:
        return None
    msg = _find_message(conv, message_id)
    if not msg or msg.get("direction") != "out":
        return None
    current = msg.get("status") or "sent"
    if not _can_advance_outbound(current, status):
        return _normalize_outbound_record(msg)
    msg["status"] = status
    if status == "read":
        msg["read_at"] = read_at or _now_iso()
    data["conversations"][key] = conv
    save_inbox(slot, data)
    return _normalize_outbound_record(msg)


def mark_outbound_delivered(slot: str, user_id: int, message_id: int) -> dict | None:
    return update_outbound_status(slot, user_id, message_id, "delivered")


def mark_conversation_read(slot: str, user_id: int) -> dict | None:
    data = load_inbox(slot)
    key = str(user_id)
    conv = data["conversations"].get(key)
    if not conv:
        return None
    conv["unread_count"] = 0
    save_inbox(slot, data)
    return conv


def repair_conversation_keys(slot: str) -> list[dict]:
    """Move conversations stored under non-numeric keys (e.g. phone_e164) to user_id keys."""
    data = load_inbox(slot)
    convs = data.get("conversations") or {}
    repairs: list[dict] = []
    for bad_key in list(convs.keys()):
        try:
            int(bad_key)
            continue
        except (TypeError, ValueError):
            pass
        conv = convs.get(bad_key) or {}
        try:
            good_key = str(int(conv.get("user_id") or bad_key))
        except (TypeError, ValueError):
            del convs[bad_key]
            repairs.append({"bad_key": bad_key, "action": "removed", "reason": "no_user_id"})
            continue
        if good_key == bad_key:
            continue
        if good_key in convs:
            del convs[bad_key]
            repairs.append({"bad_key": bad_key, "action": "removed_duplicate", "good_key": good_key})
        else:
            convs[good_key] = conv
            del convs[bad_key]
            repairs.append({"bad_key": bad_key, "action": "moved", "good_key": good_key})
    if repairs:
        data["conversations"] = convs
        save_inbox(slot, data)
    return repairs


def delete_conversation(slot: str, user_id: int) -> bool:
    """Remove a stored DM thread from the dashboard inbox (not from Telegram)."""
    data = load_inbox(slot)
    key = str(int(user_id))
    convs = data.get("conversations") or {}
    if key not in convs:
        for k, conv in list(convs.items()):
            try:
                if int(conv.get("user_id") or 0) == int(user_id):
                    key = k
                    break
            except (TypeError, ValueError):
                continue
        else:
            return False
    del convs[key]
    data["conversations"] = convs
    save_inbox(slot, data)
    return True


def list_conversations(slot: str) -> list[dict]:
    data = load_inbox(slot)
    items = []
    dirty = False
    for conv in data.get("conversations", {}).values():
        unread = int(conv.get("unread_count") or 0)
        msgs = conv.get("messages") or []
        if unread > 0 and msgs and msgs[-1].get("direction") == "out":
            conv["unread_count"] = 0
            unread = 0
            dirty = True
        items.append({
            "user_id": conv.get("user_id"),
            "username": conv.get("username") or "",
            "name": conv.get("name") or "",
            "last_message": conv.get("last_message") or "",
            "last_message_at": conv.get("last_message_at"),
            "unread_count": unread,
        })
    if dirty:
        save_inbox(slot, data)
    items.sort(key=lambda c: c.get("last_message_at") or "", reverse=True)
    return items


def _mark_outbound_read(msg: dict) -> bool:
    if msg.get("direction") != "out" or msg.get("status") == "read":
        return False
    msg["status"] = "read"
    msg["read_at"] = _now_iso()
    return True


def mark_outgoing_read_up_to(slot: str, user_id: int, max_telegram_id: int) -> list[dict]:
    """Mark outgoing messages with id <= max_telegram_id as read. Returns updated records."""
    if max_telegram_id <= 0:
        return []
    data = load_inbox(slot)
    key = str(user_id)
    conv = data.get("conversations", {}).get(key)
    if not conv:
        return []
    updated: list[dict] = []
    for m in conv.get("messages") or []:
        if m.get("direction") != "out":
            continue
        mid = int(m.get("id") or 0)
        if mid > 0 and mid <= max_telegram_id and _mark_outbound_read(m):
            updated.append(_normalize_outbound_record(m))
    if updated:
        save_inbox(slot, data)
    return updated


def mark_all_outgoing_read(slot: str, user_id: int) -> list[dict]:
    """Mark every outbound message in a thread as read (e.g. contact replied)."""
    data = load_inbox(slot)
    key = str(user_id)
    conv = data.get("conversations", {}).get(key)
    if not conv:
        return []
    updated: list[dict] = []
    for m in conv.get("messages") or []:
        if m.get("direction") == "out" and _mark_outbound_read(m):
            updated.append(_normalize_outbound_record(m))
    if updated:
        save_inbox(slot, data)
    return updated


def infer_outgoing_read_from_thread(conv: dict) -> list[dict]:
    """
    If the contact replied after our messages, treat our earlier outbound as read.
    Covers history loaded before read receipts were tracked.
    """
    msgs = conv.get("messages") or []
    if not msgs or msgs[-1].get("direction") != "in":
        return []
    updated: list[dict] = []
    for m in msgs:
        if m.get("direction") == "out" and _mark_outbound_read(m):
            updated.append(_normalize_outbound_record(m))
    return updated


def migrate_legacy_sent_to_delivered(slot: str, user_id: int) -> list[dict]:
    """Persist upgrade for old outbound rows still stored as 'sent'."""
    data = load_inbox(slot)
    key = str(user_id)
    conv = data.get("conversations", {}).get(key)
    if not conv:
        return []
    updated: list[dict] = []
    for m in conv.get("messages") or []:
        if m.get("direction") == "out" and m.get("status") == "sent":
            m["status"] = "delivered"
            updated.append(_normalize_outbound_record(m))
    if updated:
        save_inbox(slot, data)
    return updated


def get_messages(
    slot: str,
    user_id: int,
    *,
    persist_read_hints: bool = True,
) -> list[dict]:
    data = load_inbox(slot)
    key = str(user_id)
    conv = data.get("conversations", {}).get(key)
    if not conv:
        return []
    changed = False
    migrated = migrate_legacy_sent_to_delivered(slot, user_id)
    if migrated:
        changed = True
        data = load_inbox(slot)
        conv = data.get("conversations", {}).get(key) or conv
    inferred = infer_outgoing_read_from_thread(conv)
    if persist_read_hints and inferred:
        save_inbox(slot, data)
        data = load_inbox(slot)
        conv = data.get("conversations", {}).get(key, conv)
    msgs = [_normalize_outbound_record(m) for m in (conv.get("messages") or [])]
    for m in msgs:
        if m.get("media_type"):
            continue
        text = (m.get("text") or "").strip().lower()
        if text in ("[media]", "[photo]", "[image]"):
            m["media"] = True
            m["media_type"] = "photo"
        elif text == "[sticker]":
            m["media"] = True
            m["media_type"] = "sticker"
        elif not text and m.get("direction") == "in" and not m.get("media"):
            m["media"] = True
            m["media_type"] = "photo"
        elif m.get("media_type") in ("photo", "document", "media", "sticker") and text in (
            "",
            "[photo]",
            "[media]",
            "[image]",
            "[sticker]",
        ):
            m["media"] = True
    msgs.sort(key=lambda m: (m.get("timestamp") or "", int(m.get("id") or 0)))
    return msgs


def patch_message_text_by_telegram_id(
    slot: str,
    user_id: int,
    telegram_id: int,
    text: str,
) -> dict | None:
    """Replace stored message text (e.g. link body promoted from a text attachment)."""
    body = (text or "").strip()
    if not body:
        return None
    data = load_inbox(slot)
    key = str(user_id)
    conv = data.get("conversations", {}).get(key)
    if not conv:
        return None
    record = None
    for m in conv.get("messages") or []:
        if int(m.get("id") or 0) != int(telegram_id):
            continue
        m["text"] = body
        placeholder = body.lower() in (
            "[media]", "[photo]", "[image]", "[video]", "[voice]",
            "[audio]", "[document]", "[sticker]", "[file]",
        )
        if not placeholder:
            m.pop("media", None)
            m.pop("media_type", None)
        record = m
        break
    if not record:
        return None
    preview = body if len(body) <= 200 else body[:197] + "..."
    if (conv.get("last_message_at") or "") <= (record.get("timestamp") or ""):
        conv["last_message"] = preview
    save_inbox(slot, data)
    return record


def build_slot_payload(slot: str) -> dict:
    return {
        "slot": slot,
        "conversations": list_conversations(slot),
        "updated_at": load_inbox(slot).get("updated_at"),
    }
