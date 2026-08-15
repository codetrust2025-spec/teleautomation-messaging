"""Auto-send UltraViewer + LockedIn demo install links after demo timing is confirmed."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([^/?#]+)", re.I)


def normalize_drive_share_url(url: str) -> str:
    """Prefer direct download links for Google Drive file shares."""
    raw = (url or "").strip()
    if not raw:
        return ""
    m = _DRIVE_FILE_RE.search(raw)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return raw

WIN_LOCKEDIN = "DEMO_TOOLS_LOCKEDIN_WINDOWS_URL"
MAC_LOCKEDIN = "DEMO_TOOLS_LOCKEDIN_MAC_URL"
ULTRAVIEWER = "DEMO_TOOLS_ULTRAVIEWER_URL"
LEGACY_LOCKEDIN = "DEMO_TOOLS_LOCKEDIN_URL"
FOLDER = "DEMO_TOOLS_FOLDER_URL"


def _env_url(*names: str) -> str:
    for name in names:
        val = normalize_drive_share_url((os.environ.get(name) or "").strip())
        if val:
            return val
    return ""


def _tool_catalog() -> tuple[list[dict], str]:
    folder = _env_url(FOLDER)
    win_url = _env_url(WIN_LOCKEDIN, LEGACY_LOCKEDIN)
    mac_url = _env_url(MAC_LOCKEDIN)
    ultra_url = _env_url(ULTRAVIEWER)
    tools = [
        {
            "id": "lockedin_windows",
            "name": "LockedIn AI (Windows)",
            "description": "Interview support app for Windows",
            "filename": "LockedIn-Windows",
            "client_url": win_url,
            "available": bool(win_url),
        },
        {
            "id": "lockedin_mac",
            "name": "LockedIn AI (Mac)",
            "description": "Interview support app for Mac",
            "filename": "LockedIn-Mac",
            "client_url": mac_url,
            "available": bool(mac_url),
        },
        {
            "id": "ultraviewer",
            "name": "UltraViewer",
            "description": "Remote desktop for the live demo",
            "filename": "UltraViewer",
            "client_url": ultra_url,
            "available": bool(ultra_url),
        },
    ]
    return tools, folder


def catalog_payload() -> dict:
    tools, folder = _tool_catalog()
    delivery = (os.environ.get("DEMO_TOOLS_DELIVERY") or "drive").strip().lower()
    return {
        "status": "ok",
        "delivery": delivery,
        "folder_url": folder or None,
        "tools": tools,
    }


def _compose_message() -> str | None:
    tools, folder = _tool_catalog()
    lines = [
        "Here are the install links for your demo 👇",
        "",
    ]
    for tool in tools:
        url = (tool.get("client_url") or "").strip()
        if url:
            lines.append(f"• {tool['name']}: {url}")
    if folder:
        lines.extend(["", f"All files (Drive): {folder}"])
    body = "\n".join(lines).strip()
    if not any(t.get("available") for t in tools) and not folder:
        return None
    return body


def _already_sent(slot: str, user_id: int, lead: dict | None) -> bool:
    from core.ai_smart_reply_store import get_lead_state

    state = get_lead_state(slot, user_id)
    if state.get("demo_tools_sent_at"):
        return True
    graph = (lead or {}).get("graph") or {}
    return bool(graph.get("demo_tools_sent_at"))


def _demo_timing_confirmed(
    *,
    user_text: str,
    history: list[dict] | None,
    qualification: dict | None,
) -> bool:
    qual = qualification or {}
    if (qual.get("demo_timing") or "").strip():
        return True
    try:
        from core.ai_smart_reply import _user_gave_explicit_demo_timing

        return _user_gave_explicit_demo_timing(user_text, history)
    except Exception:
        return False


async def send_demo_tools(
    slot: str,
    user_id: int,
    *,
    sent_by: str = "ai",
) -> dict:
    """Send install links to the lead (manual or auto)."""
    text = _compose_message()
    if not text:
        return {"ok": False, "reason": "not_configured"}

    from services.whatsapp_dispatch import dispatch_lead_reply

    await dispatch_lead_reply(slot, int(user_id), text, sent_by=sent_by)
    now = datetime.now(timezone.utc).isoformat()
    from core.ai_smart_reply_store import update_lead_state

    update_lead_state(slot, int(user_id), demo_tools_sent_at=now)
    return {"ok": True, "sent_at": now}


async def maybe_auto_send_demo_tools(
    slot: str,
    user_id: int,
    *,
    user_text: str = "",
    history: list[dict] | None = None,
    qualification: dict | None = None,
    lead: dict | None = None,
) -> dict:
    """Send demo tool links once after the client confirms demo timing."""
    if _already_sent(slot, user_id, lead):
        return {"ok": False, "reason": "already_sent"}
    if not _demo_timing_confirmed(
        user_text=user_text,
        history=history,
        qualification=qualification,
    ):
        return {"ok": False, "reason": "demo_timing_missing"}
    return await send_demo_tools(slot, user_id, sent_by="ai")
