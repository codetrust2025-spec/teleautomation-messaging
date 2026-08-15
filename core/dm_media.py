"""Telegram DM media detection and on-disk cache paths."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from core.config import STATE_DIR

logger = logging.getLogger(__name__)

_MEDIA_PLACEHOLDERS = {
    "photo": "[photo]",
    "video": "[video]",
    "voice": "[voice]",
    "audio": "[audio]",
    "document": "[document]",
    "sticker": "[sticker]",
    "media": "[media]",
}

_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".bin": "application/octet-stream",
}


def media_placeholder(media_type: str) -> str:
    return _MEDIA_PLACEHOLDERS.get(media_type or "", "[media]")


def message_media_meta(msg) -> dict | None:
    """Inspect a Telethon Message; return media flags for inbox storage."""
    media = getattr(msg, "media", None)
    if not media:
        return None

    if _is_non_downloadable_media(media):
        return None

    kind = _classify_telethon_media(media)
    if not kind:
        kind = "media"
    return {
        "media": True,
        "media_type": kind,
        "placeholder": media_placeholder(kind),
    }


def _is_non_downloadable_media(media) -> bool:
    """Link previews and similar — show message text only, not as inbox attachments."""
    try:
        from telethon.tl.types import (
            MessageMediaContact,
            MessageMediaGeo,
            MessageMediaGeoLive,
            MessageMediaPoll,
            MessageMediaVenue,
            MessageMediaWebPage,
            MessageMediaWebPageEmpty,
        )
    except ImportError:
        name = type(media).__name__
        return "WebPage" in name or name in {
            "MessageMediaGeo",
            "MessageMediaGeoLive",
            "MessageMediaContact",
            "MessageMediaVenue",
            "MessageMediaPoll",
        }
    return isinstance(
        media,
        (
            MessageMediaWebPage,
            MessageMediaWebPageEmpty,
            MessageMediaGeo,
            MessageMediaGeoLive,
            MessageMediaContact,
            MessageMediaVenue,
            MessageMediaPoll,
        ),
    )


def _classify_telethon_media(media) -> str | None:
    try:
        from telethon.tl.types import (
            DocumentAttributeAnimated,
            DocumentAttributeAudio,
            DocumentAttributeSticker,
            DocumentAttributeVideo,
            MessageMediaDocument,
            MessageMediaPhoto,
        )
    except ImportError:
        return "media"

    if isinstance(media, MessageMediaPhoto):
        return "photo"

    if isinstance(media, MessageMediaDocument):
        doc = getattr(media, "document", None)
        if not doc:
            return "document"
        mime = (getattr(doc, "mime_type", None) or "").lower()
        attrs = getattr(doc, "attributes", None) or []
        for attr in attrs:
            if isinstance(attr, DocumentAttributeSticker):
                return "sticker"
            if isinstance(attr, DocumentAttributeVideo):
                return "video"
            if isinstance(attr, DocumentAttributeAudio):
                return "voice" if getattr(attr, "voice", False) else "audio"
            if isinstance(attr, DocumentAttributeAnimated):
                return "video"
        if mime.startswith("image/"):
            return "photo"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("audio/"):
            return "audio"
        return "document"

    return "media"


def media_cache_dir(slot: str) -> str:
    path = os.path.join(STATE_DIR, slot, "dm_media_cache")
    os.makedirs(path, exist_ok=True)
    return path


def media_cache_path(slot: str, user_id: int, message_id: int, ext: str = "") -> str:
    base = os.path.join(media_cache_dir(slot), f"{int(user_id)}_{int(message_id)}")
    return base + (ext if ext.startswith(".") else f".{ext}" if ext else "")


def sniff_cached_mime(path: str) -> str | None:
    """Detect real MIME from file magic (extension can lie, e.g. TGS saved as .webp)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    if len(head) >= 2 and head[:2] == b"\x1f\x8b":
        return "application/gzip"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if len(head) >= 3 and head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(head) >= 8 and head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"%PDF":
        return "application/pdf"
    if len(head) >= 4 and head[:4] == b"PK\x03\x04":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if head[:4] == b"\x00\x00\x00" or head[:3] == b"ID3":
        return "audio/mpeg"
    return None


def is_probably_text_attachment(path: str) -> bool:
    """Telegram sometimes stores link-only payloads as a small UTF-8 'document'."""
    try:
        with open(path, "rb") as fh:
            sample = fh.read(8192)
    except OSError:
        return False
    if not sample or b"\x00" in sample[:512]:
        return False
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if not text.strip():
        return False
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t")
    return printable / max(len(text), 1) > 0.85


def read_text_attachment(path: str, limit: int = 8000) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit).strip()
    except OSError:
        return ""


def is_displayable_inbox_image(path: str) -> bool:
    mime = sniff_cached_mime(path)
    return bool(mime and mime.startswith("image/"))


def mime_for_cached_file(path: str) -> str:
    sniffed = sniff_cached_mime(path)
    if sniffed:
        return sniffed
    _, ext = os.path.splitext(path)
    return _MIME_BY_EXT.get(ext.lower(), "application/octet-stream")


def is_usable_cached_media(path: str, media_type: str | None = None) -> bool:
    """True if cached bytes can be served (images, PDFs, video, docs — not gzip/TGS)."""
    if not path or not os.path.isfile(path) or os.path.getsize(path) <= 0:
        return False
    sniff = sniff_cached_mime(path)
    if sniff == "application/gzip":
        return False
    if media_type in ("photo", "sticker"):
        return is_displayable_inbox_image(path)
    return True


def finalize_cached_download(path: str | None, media_type: str) -> tuple[str, str] | None:
    """Validate downloaded cache file; remove junk; return path + mime."""
    if not path or not os.path.isfile(path):
        return None
    if is_usable_cached_media(path, media_type):
        return path, mime_for_cached_file(path)
    try:
        os.remove(path)
    except OSError:
        pass
    return None


def find_cached_media(slot: str, user_id: int, message_id: int) -> tuple[str, str] | None:
    """Return (file_path, mime_type) if a cached attachment exists."""
    directory = media_cache_dir(slot)
    prefix = f"{int(user_id)}_{int(message_id)}"
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    best: tuple[str, str] | None = None
    for name in sorted(names):
        if not name.startswith(prefix):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            continue
        sniff = sniff_cached_mime(path)
        if sniff == "application/gzip":
            continue
        if is_probably_text_attachment(path):
            continue
        entry = (path, mime_for_cached_file(path))
        if sniff and sniff.startswith("image/"):
            return entry
        if best is None:
            best = entry
    return best


def clear_media_cache_for_user(slot: str, user_id: int) -> int:
    """Delete cached inbox media files for one chat. Returns files removed."""
    directory = media_cache_dir(slot)
    prefix = f"{int(user_id)}_"
    removed = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        if not name.startswith(prefix):
            continue
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


OUTBOUND_UPLOAD_MAX_BYTES = 25 * 1024 * 1024


def classify_outbound_upload(filename: str, content_type: str = "") -> dict:
    """Map an uploaded file to inbox media_type + Telethon send_file kwargs."""
    name = (filename or "").lower()
    mime = (content_type or "").lower().split(";")[0].strip()
    if not mime:
        _, ext = os.path.splitext(name)
        mime = _MIME_BY_EXT.get(ext, "application/octet-stream")

    # Browser voice recorder uploads voice-<ts>.webm; ext-only sniff can be video/webm.
    if name.startswith("voice-") and name.endswith(".webm"):
        return {
            "mime": "audio/webm",
            "media_type": "voice",
            "voice_note": True,
            "force_document": False,
        }

    voice_note = False
    force_document = False
    media_type = "document"

    if mime.startswith("image/"):
        media_type = "photo"
        if mime not in ("image/jpeg", "image/jpg", "image/png", "image/webp"):
            force_document = True
    elif mime.startswith("video/"):
        media_type = "video"
    elif mime.startswith("audio/"):
        if mime in ("audio/ogg", "audio/opus", "audio/webm") or name.endswith((".ogg", ".opus")):
            media_type = "voice"
            voice_note = True
        else:
            media_type = "audio"
    elif mime == "application/pdf":
        media_type = "document"
        force_document = True
    else:
        force_document = True

    return {
        "mime": mime,
        "media_type": media_type,
        "voice_note": voice_note,
        "force_document": force_document,
    }


def transcode_voice_upload_to_ogg(src_path: str) -> str | None:
    """Convert WebM/MP3/etc. to OGG/Opus — required for Telegram voice-note bubbles."""
    if not src_path or not os.path.isfile(src_path):
        return None
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg not found; outbound voice may arrive as a file attachment")
        return None
    base, _ = os.path.splitext(src_path)
    dest = f"{base}_telegram_voice.ogg"
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        src_path,
        "-vn",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-application",
        "voip",
        dest,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=90, check=False)
        if result.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) <= 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")[:300]
            logger.warning("voice transcode failed (%s): %s", result.returncode, err)
            try:
                if os.path.isfile(dest):
                    os.remove(dest)
            except OSError:
                pass
            return None
        return dest
    except Exception as e:
        logger.warning("voice transcode error: %s", e)
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass
        return None


def resolve_outbound_voice_path(
    file_path: str,
    filename: str = "",
    content_type: str = "",
) -> tuple[str, str | None, str]:
    """
    Return (path_to_send, temp_path_to_delete, effective_filename).
    Telegram voice notes must be OGG/Opus — transcode browser WebM when needed.
    """
    info = classify_outbound_upload(filename, content_type)
    send_name = filename or os.path.basename(file_path) or "upload"
    if not info.get("voice_note"):
        return file_path, None, send_name

    name = send_name.lower()
    mime = (info.get("mime") or "").lower()
    _, ext = os.path.splitext(name)
    if not ext:
        _, ext = os.path.splitext(file_path.lower())

    if ext == ".ogg" and mime in ("audio/ogg", "audio/opus", "application/ogg"):
        return file_path, None, send_name

    converted = transcode_voice_upload_to_ogg(file_path)
    if converted:
        return converted, converted, "voice.ogg"

    return file_path, None, send_name


def ext_for_upload(filename: str, content_type: str, media_type: str) -> str:
    name = (filename or "").lower()
    _, ext = os.path.splitext(name)
    if ext and len(ext) <= 8:
        return ext
    mime = (content_type or "").lower().split(";")[0].strip()
    if media_type == "photo":
        if "png" in mime:
            return ".png"
        if "webp" in mime:
            return ".webp"
        if "gif" in mime:
            return ".gif"
        return ".jpg"
    if media_type == "video":
        return ".mp4"
    if media_type in ("voice", "audio"):
        return ".ogg"
    if "pdf" in mime:
        return ".pdf"
    return ".bin"


def guess_download_ext(msg, media_type: str) -> str:
    if media_type == "sticker":
        return ".webp"
    if media_type == "photo":
        return ".jpg"
    if media_type == "video":
        return ".mp4"
    if media_type in ("voice", "audio"):
        return ".ogg"
    doc = getattr(getattr(msg, "media", None), "document", None)
    mime = (getattr(doc, "mime_type", None) or "").lower()
    if "pdf" in mime:
        return ".pdf"
    if "word" in mime or "msword" in mime:
        return ".docx" if "openxml" in mime else ".doc"
    if "webp" in mime:
        return ".webp"
    if "png" in mime:
        return ".png"
    if "gif" in mime:
        return ".gif"
    if "jpeg" in mime or "jpg" in mime:
        return ".jpg"
    return ".bin"
