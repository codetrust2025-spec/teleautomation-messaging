"""Count groups/channels the logged-in account has already joined (Telegram dialogs)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any  # noqa: F401 used in return type

from telethon import TelegramClient
from telethon.tl import functions, types

logger = logging.getLogger(__name__)

# Cap scan time so UI refresh does not hang on huge accounts
JOINED_STATS_TIMEOUT_SECONDS = 180


def _classify_dialog(dialog) -> tuple[str, str]:
    """
    Classify a dialog for membership counting.
    Returns (category, skip_reason) where category is group|channel|user|skipped.
    """
    entity = dialog.entity
    if isinstance(entity, types.User):
        return "user", "private_chat"
    if isinstance(entity, (types.Chat, types.ChatForbidden)):
        if getattr(entity, "migrated_to", None):
            return "skipped", "migrated_basic_group"
        if getattr(entity, "deactivated", False):
            return "skipped", "deactivated_chat"
        return "group", ""
    if isinstance(entity, types.Channel):
        if getattr(entity, "left", False):
            return "skipped", "left_channel"
        if getattr(entity, "megagroup", False):
            return "group", ""
        if getattr(entity, "broadcast", False):
            return "channel", ""
        return "channel", "channel_unknown_type"
    if isinstance(entity, types.ChannelForbidden):
        if getattr(entity, "megagroup", False):
            return "group", ""
        return "channel", ""
    return "skipped", f"unknown_entity_{type(entity).__name__}"


async def _discover_folder_ids(client: TelegramClient) -> list[int]:
    """Main list (0), archive (1), and any custom dialog filters."""
    folders: set[int] = {0, 1}
    try:
        result = await client(functions.messages.GetDialogFiltersRequest())
        for item in result or []:
            fid = getattr(item, "id", None)
            if isinstance(fid, int) and fid >= 0:
                folders.add(fid)
    except Exception as e:
        logger.debug("GetDialogFilters failed: %s", e)
    return sorted(folders)


async def _iter_membership_dialogs(client: TelegramClient):
    """
    Yield each group/channel dialog once across all Telegram folders.

    Telethon folder=None does not always include archived/custom folders; scan each
    folder explicitly and dedupe by marked peer id.
    """
    seen: set[int] = set()
    folder_ids = await _discover_folder_ids(client)
    errors: list[str] = []
    yielded = 0

    for folder_id in folder_ids:
        try:
            async for dialog in client.iter_dialogs(
                limit=None,
                folder=folder_id,
                ignore_migrated=True,
            ):
                if dialog.id in seen:
                    continue
                seen.add(dialog.id)
                yielded += 1
                yield dialog, folder_id
        except Exception as e:
            msg = f"folder={folder_id}: {type(e).__name__}: {e}"
            errors.append(msg)
            logger.warning("iter_dialogs(%s) failed: %s", folder_id, e)

    # Catch-all for dialogs not tied to a known folder id
    try:
        async for dialog in client.iter_dialogs(limit=None, ignore_migrated=True):
            if dialog.id in seen:
                continue
            seen.add(dialog.id)
            yielded += 1
            yield dialog, -1
    except Exception as e:
        msg = f"folder=default: {type(e).__name__}: {e}"
        errors.append(msg)
        logger.warning("iter_dialogs(default) failed: %s", e)

    if yielded == 0 and errors:
        raise RuntimeError(
            "Dialog scan failed — session may be locked by a running worker. "
            + "; ".join(errors[:4])
        )


async def fetch_joined_dialog_details(client: TelegramClient) -> dict[str, Any]:
    """
    Return joined group/channel rows and scan metadata.

    Each target record:
        {id, type ("group"|"channel"), name, username, link, members?}

    Keys: targets, partial, partial_reason, count
    """
    started = time.monotonic()
    out: list[dict] = []
    seen_ids: set[int] = set()
    timed_out = False

    async for dialog, _folder in _iter_membership_dialogs(client):
        category, _reason = _classify_dialog(dialog)
        if category not in ("group", "channel"):
            continue
        ent = dialog.entity
        ent_id = getattr(ent, "id", None)
        if not isinstance(ent_id, int) or ent_id in seen_ids:
            continue
        seen_ids.add(ent_id)
        username = (getattr(ent, "username", None) or "").strip()
        name = (getattr(ent, "title", None) or "").strip()
        link = f"https://t.me/{username}" if username else ""
        members = getattr(ent, "participants_count", None)
        out.append({
            "id": ent_id,
            "type": category,
            "name": name,
            "username": username,
            "link": link,
            "members": int(members) if isinstance(members, int) else None,
        })
        if time.monotonic() - started > JOINED_STATS_TIMEOUT_SECONDS:
            logger.warning("fetch_joined_dialog_details timeout after %s entries", len(out))
            timed_out = True
            break

    partial_reason = ""
    if timed_out:
        partial_reason = (
            f"Scan stopped after {JOINED_STATS_TIMEOUT_SECONDS}s — "
            f"only {len(out)} groups loaded; refresh again or use fewer accounts"
        )

    return {
        "targets": out,
        "partial": timed_out,
        "partial_reason": partial_reason,
        "count": len(out),
    }


async def fetch_joined_counts(client: TelegramClient) -> dict:
    """
    Scan account dialogs across all folders once.
    Returns joined_groups (incl. supergroups), joined_channels (broadcast), joined_total.
    """
    groups = 0
    channels = 0
    total_dialogs = 0
    skipped: Counter[str] = Counter()
    folder_hits: Counter[int] = Counter()
    started = time.monotonic()
    folder_ids = await _discover_folder_ids(client)

    async def _scan() -> None:
        nonlocal groups, channels, total_dialogs
        async for dialog, folder_id in _iter_membership_dialogs(client):
            total_dialogs += 1
            folder_hits[folder_id] += 1
            category, reason = _classify_dialog(dialog)
            if category == "group":
                groups += 1
            elif category == "channel":
                channels += 1
            elif category == "user":
                skipped[reason or "private_chat"] += 1
            else:
                skipped[reason or "skipped"] += 1

            elapsed = time.monotonic() - started
            if elapsed > JOINED_STATS_TIMEOUT_SECONDS:
                raise asyncio.TimeoutError(
                    f"joined scan exceeded {JOINED_STATS_TIMEOUT_SECONDS}s after {total_dialogs} dialogs"
                )

    timed_out = False
    partial_reason = ""
    try:
        await _scan()
    except asyncio.TimeoutError:
        timed_out = True
        partial_reason = (
            f"Scan stopped after {JOINED_STATS_TIMEOUT_SECONDS}s — "
            f"only {total_dialogs} dialogs scanned; refresh again for full counts"
        )
        logger.warning(
            "joined_scan partial timeout after %ss — dialogs=%s groups=%s channels=%s",
            int(time.monotonic() - started),
            total_dialogs,
            groups,
            channels,
        )

    total = groups + channels
    elapsed_s = round(time.monotonic() - started, 2)
    scan_debug: dict[str, Any] = {
        "total_dialogs": total_dialogs,
        "groups": groups,
        "channels": channels,
        "skipped": dict(skipped),
        "folders_scanned": folder_ids,
        "folder_hits": {str(k): v for k, v in sorted(folder_hits.items())},
        "elapsed_seconds": elapsed_s,
        "partial": timed_out,
        "partial_reason": partial_reason,
    }

    logger.info(
        "joined_scan complete: dialogs=%s groups=%s channels=%s skipped=%s "
        "folders=%s elapsed=%ss",
        total_dialogs,
        groups,
        channels,
        dict(skipped),
        folder_ids,
        elapsed_s,
    )
    for reason, count in sorted(skipped.items()):
        logger.info("joined_scan skipped: %s × %s", reason, count)

    premium = False
    try:
        me = await client.get_me()
        premium = bool(getattr(me, "premium", False))
    except Exception:
        pass

    from core.subscription_accounts import classify_account_info

    partial = {
        "joined_groups": groups,
        "joined_channels": channels,
        "joined_total": total,
        "telegram_premium": premium,
    }
    from core.ist_time import format_ist_storage_label

    return {
        "joined_groups": groups,
        "joined_channels": channels,
        "joined_total": total,
        "joined_updated_at": format_ist_storage_label(),
        "telegram_premium": premium,
        "is_subscription": classify_account_info(partial),
        "_scan_debug": scan_debug,
    }
