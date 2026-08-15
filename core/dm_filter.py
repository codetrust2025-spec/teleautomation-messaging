"""Strict filters — private 1-to-1 human DMs only (no groups/channels/bots)."""

from __future__ import annotations

from telethon.tl.types import Channel, Chat, User


def is_private_user_entity(entity) -> bool:
    """True if entity is an individual user (not bot)."""
    if not isinstance(entity, User):
        return False
    if getattr(entity, "deleted", False):
        return False
    if getattr(entity, "bot", False):
        return False
    return True


def is_private_dm_chat(chat) -> bool:
    """Reject groups, supergroups, channels, and bots."""
    if chat is None:
        return False
    if isinstance(chat, (Channel, Chat)):
        return False
    return is_private_user_entity(chat)


async def validate_incoming_dm(event) -> tuple[bool, dict | None]:
    """
    Returns (ok, meta) where meta has user_id, username, name for storage.
    Strict: private chat + human sender + not self.
    """
    if not getattr(event, "is_private", False):
        return False, None

    try:
        chat = await event.get_chat()
    except Exception:
        return False, None

    if not is_private_dm_chat(chat):
        return False, None

    try:
        sender = await event.get_sender()
    except Exception:
        sender = None

    if sender is not None and not is_private_user_entity(sender):
        return False, None

    peer = chat if isinstance(chat, User) else sender
    if peer is None or not is_private_user_entity(peer):
        return False, None

    return True, _peer_meta(peer)


def _peer_meta(peer: User) -> dict:
    user_id = int(peer.id)
    username = (getattr(peer, "username", None) or "").strip()
    first = (getattr(peer, "first_name", None) or "").strip()
    last = (getattr(peer, "last_name", None) or "").strip()
    name = " ".join(p for p in (first, last) if p).strip() or username or str(user_id)
    return {"user_id": user_id, "username": username, "name": name}


async def validate_outgoing_dm(event) -> tuple[bool, dict | None]:
    """Outgoing private DM to an individual user (not group/channel/bot)."""
    if not getattr(event, "is_private", False):
        return False, None

    try:
        chat = await event.get_chat()
    except Exception:
        return False, None

    if not is_private_dm_chat(chat):
        return False, None

    return True, _peer_meta(chat)


def display_username(username: str | None, user_id: int) -> str:
    u = (username or "").strip().lstrip("@")
    return f"@{u}" if u else f"user_{user_id}"
