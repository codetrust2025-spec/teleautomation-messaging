"""On-disk cache for inbound WhatsApp media."""

from __future__ import annotations

import os

from core.config import STATE_DIR
from core.dm_media import mime_for_cached_file


def wa_media_cache_dir(slot: str) -> str:
    path = os.path.join(STATE_DIR, slot, "wa_media_cache")
    os.makedirs(path, exist_ok=True)
    return path


def _file_prefix(user_id: int, message_id: int) -> str:
    return f"{int(user_id)}_{int(message_id)}"


def media_exists(slot: str, user_id: int, message_id: int) -> str | None:
    """Return cached file path if present."""
    directory = wa_media_cache_dir(slot)
    prefix = _file_prefix(user_id, message_id)
    try:
        for name in sorted(os.listdir(directory)):
            if not name.startswith(prefix):
                continue
            path = os.path.join(directory, name)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return path
    except OSError:
        pass
    return None


def save_media(
    slot: str,
    user_id: int,
    message_id: int,
    data: bytes,
    *,
    ext: str = "jpg",
) -> str:
    directory = wa_media_cache_dir(slot)
    clean_ext = (ext or "jpg").lstrip(".").lower()[:8] or "jpg"
    path = os.path.join(directory, f"{_file_prefix(user_id, message_id)}.{clean_ext}")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def public_media_url(slot: str, user_id: int, message_id: int) -> str:
    return f"/inbox/{slot}/wa-media/{int(user_id)}/{int(message_id)}"


def resolve_media_file(slot: str, user_id: int, message_id: int) -> tuple[str, str] | None:
    """Return (path, mime) for a cached WA attachment."""
    path = media_exists(slot, user_id, message_id)
    if not path:
        return None
    return path, mime_for_cached_file(path)
