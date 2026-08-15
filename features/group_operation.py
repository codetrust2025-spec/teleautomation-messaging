"""
Atomic per-group operation for the account worker.
Decision engine: recent-message check → send → join-if-needed → classify errors.
"""

import random
import re
from typing import Any

from telethon import TelegramClient

from core.config import FLOOD_HARD_BAN_SECONDS, RECENT_MESSAGE_LIMIT
from core.structured_logging import LogEvent
from features.delay_handler import wait_seconds
from features.logging_feature import AccountLogger

from telethon.errors import ChatAdminRequiredError

OpResult = str | tuple[str, dict[str, Any]]


def _flood(seconds: int, *, api: str) -> OpResult:
    """api: which Telethon call raised FloodWait (for logs / debugging)."""
    return ("flood", {"seconds": int(seconds), "api": api})


def _classify_send_error(exc: Exception) -> str | OpResult:
    """Map Telethon errors to result codes — no logging here (worker logs once)."""
    from telethon.errors import (
        FloodWaitError,
        ChatWriteForbiddenError,
        UserBannedInChannelError,
        UsernameNotOccupiedError,
        UsernameInvalidError,
        ChannelPrivateError,
        ChatRestrictedError,
        ChannelsTooMuchError,
        InviteHashInvalidError,
        InviteRequestSentError,
    )

    if isinstance(exc, FloodWaitError):
        return _flood(exc.seconds, api="classified_error")  # type: ignore[return-value]
    if isinstance(exc, (UsernameNotOccupiedError, UsernameInvalidError)):
        return "invalid"
    if isinstance(exc, (ChannelPrivateError, UserBannedInChannelError, ChatRestrictedError)):
        return "blocked"
    if isinstance(exc, ChatAdminRequiredError):
        return "blocked"
    if isinstance(exc, ChatWriteForbiddenError):
        return "cant_write"
    if isinstance(exc, ChannelsTooMuchError):
        return "blocked"
    if isinstance(exc, (InviteHashInvalidError, InviteRequestSentError)):
        return "blocked"

    err = str(exc).lower()
    if "admin privileges" in err or "chat_admin" in err:
        return "blocked"
    if "private" in err or "banned" in err:
        return "blocked"
    if "username" in err or "no user" in err or "not occupied" in err:
        return "invalid"
    if "topic_closed" in err or "restricted" in err or "can't write" in err:
        return "blocked"
    if "broadcast" in err or ("channel" in err and "write" in err):
        return "blocked"
    if "too many" in err and ("channel" in err or "join" in err):
        return "blocked"
    if "invite" in err or "approval" in err:
        return "blocked"
    if "disconnected" in err or "not connected" in err or "database is locked" in err:
        return ("error", {"detail": str(exc).strip()[:300], "session": True})
    if "invalid channel object" in err or "channelinvalid" in err:
        return "invalid"
    return "error"


def _wrap_error(exc: Exception) -> OpResult:
    """Return classified code, with Telegram detail when generic error."""
    code = _classify_send_error(exc)
    if isinstance(code, tuple):
        return code
    if code == "error":
        detail = str(exc).strip().replace("\n", " ")[:300]
        return ("error", {"detail": detail or "unknown"})
    return code


def _sender_id(message, my_id: int) -> int | None:
    sid = getattr(message, "sender_id", None)
    if sid is not None:
        return int(sid) if sid else None
    from_id = getattr(message, "from_id", None)
    if from_id is None:
        return None
    if hasattr(from_id, "user_id"):
        return int(from_id.user_id)
    return int(from_id) if from_id else None


def _is_service_message(message) -> bool:
    from telethon.tl.types import MessageService

    return isinstance(message, MessageService)


def _message_body(message) -> str:
    return (getattr(message, "message", None) or getattr(message, "text", None) or "").strip()


def _normalize_message_for_compare(text: str) -> str:
    """Collapse whitespace and strip leading emoji for fuzzy campaign compare."""
    s = re.sub(r"\s+", " ", (text or "").strip().lower())
    s = re.sub(r"^[\U0001F300-\U0001FAFF\U00002600-\U000027BF\s]+", "", s)
    return s.strip()


def _messages_similar(existing: str, planned: str) -> bool:
    """True only when recent self-post matches planned text exactly (after normalize)."""
    a = _normalize_message_for_compare(existing)
    b = _normalize_message_for_compare(planned)
    return bool(a and b and a == b)


async def _needs_resend(
    client: TelegramClient,
    group: str,
    my_id: int,
    text: str | None = None,
) -> bool | OpResult:
    """
    Fetch last N messages; skip send if any recent non-service message is ours
    with the same (or very similar) body as *text* when provided.

    When *text* is set, a recent self-post with different campaign copy still
    allows send — fixes stale skips after fleet message updates / rewrites.

    Returns OpResult flood tuple if get_messages hits FloodWait.
    """
    limit = max(1, RECENT_MESSAGE_LIMIT)

    def _check(msgs) -> bool:
        if not msgs:
            return True
        for msg in msgs:
            if _is_service_message(msg):
                continue
            if _sender_id(msg, my_id) != my_id:
                continue
            if text and not _messages_similar(_message_body(msg), text):
                continue
            return False
        return True

    try:
        messages = await _telegram_op_with_retry(
            "get_messages",
            lambda: client.get_messages(group, limit=limit),
        )
        if isinstance(messages, tuple):
            return messages
        return _check(messages)
    except Exception:
        return True


async def _wait_small_flood(seconds: int) -> None:
    if seconds >= FLOOD_HARD_BAN_SECONDS:
        return
    await wait_seconds(int(seconds) + random.randint(2, 15))


_TELEGRAM_OP_RETRIES = 2


async def _telegram_op_with_retry(
    op_name: str,
    factory,
    *,
    should_continue=None,
) -> Any:
    """Retry transient errors and small FloodWait inside a single group op."""
    from telethon.errors import FloodWaitError

    last_flood: int | None = None
    for attempt in range(_TELEGRAM_OP_RETRIES + 1):
        try:
            return await factory()
        except FloodWaitError as e:
            last_flood = int(e.seconds)
            if last_flood >= FLOOD_HARD_BAN_SECONDS:
                return _flood(last_flood, api=op_name)
            if attempt >= _TELEGRAM_OP_RETRIES:
                return _flood(last_flood, api=op_name)
            await _wait_small_flood(last_flood)
        except Exception as e:
            err = str(e).lower()
            transient = any(
                x in err
                for x in (
                    "database is locked",
                    "disconnected",
                    "not connected",
                    "timeout",
                    "connection",
                )
            )
            if transient and attempt < _TELEGRAM_OP_RETRIES:
                await wait_seconds(2 * (attempt + 1), should_continue)
                continue
            raise
    if last_flood is not None:
        return _flood(last_flood, api=op_name)
    return "error"


async def _join(client: TelegramClient, group: str) -> OpResult:
    from telethon.errors import (
        FloodWaitError,
        ChannelPrivateError,
        UserBannedInChannelError,
        ChatWriteForbiddenError,
        UserAlreadyParticipantError,
    )
    from telethon.tl.functions.channels import JoinChannelRequest

    try:
        await client(JoinChannelRequest(group))
        await wait_seconds(random.uniform(2, 5))
        return "joined_new"
    except UserAlreadyParticipantError:
        await wait_seconds(random.uniform(1, 3))
        return "already_in"
    except FloodWaitError as e:
        if e.seconds >= FLOOD_HARD_BAN_SECONDS:
            return _flood(e.seconds, api="join_channel")
        await _wait_small_flood(e.seconds)
        try:
            await client(JoinChannelRequest(group))
            await wait_seconds(random.uniform(2, 5))
            return "joined_new"
        except FloodWaitError as e2:
            return _flood(e2.seconds, api="join_channel")
        except Exception as exc:
            return _wrap_error(exc)
    except (ChannelPrivateError, UserBannedInChannelError, ChatWriteForbiddenError):
        return "blocked"
    except Exception as e:
        return _wrap_error(e)


async def _send(client: TelegramClient, group: str, text: str) -> OpResult:
    try:
        result = await _telegram_op_with_retry(
            "send_message",
            lambda: client.send_message(group, text),
        )
    except Exception as e:
        return _wrap_error(e)
    if isinstance(result, tuple):
        return result
    return "ok"


async def _execute_join_path(
    client: TelegramClient,
    group: str,
    text: str,
    logger: AccountLogger,
    *,
    send_after: bool,
    health_score: float = 100.0,
    speed_mode: str = "normal",
) -> OpResult:
    from core.join_cycle import (
        evaluate_join,
        record_join_attempt,
        record_join_failure,
        record_join_success,
    )
    from core.unified_scheduler import post_join_delay_seconds

    decision = evaluate_join(logger.slot, group)
    if not decision.allowed:
        await logger.log_event(
            LogEvent.JOIN_SKIP,
            "info",
            group=group,
            reason=decision.message,
            wait_sec=decision.wait_seconds,
        )
        return "join_limited"

    record_join_attempt(logger.slot)
    await logger.log_event(LogEvent.JOIN_ATTEMPT, "info", group=group)
    join_result = await _join(client, group)

    if join_result == "joined_new":
        delay = post_join_delay_seconds(health_score=health_score, speed_mode=speed_mode)
        await logger.log_event(
            LogEvent.JOIN_SUCCESS,
            "info",
            group=group,
            new_join=True,
            post_delay_sec=int(delay),
        )
        await wait_seconds(delay)

    if join_result in ("joined_new", "already_in"):
        if not send_after:
            if join_result == "joined_new":
                record_join_success(logger.slot)
                return ("pre_joined", {"new_join": True})
            return ("pre_joined", {"new_join": False})
        post_result = await _send(client, group, text)
        if post_result == "ok":
            if join_result == "joined_new":
                record_join_success(logger.slot)
            return "joined_sent"
        if post_result == "cant_write":
            return "blocked"
        return post_result

    backoff = record_join_failure(logger.slot, group)
    await logger.log_event(
        LogEvent.JOIN_FAIL,
        "warning",
        group=group,
        result=str(join_result),
        backoff_sec=backoff,
    )
    if join_result in ("invalid", "blocked"):
        return join_result
    return join_result


async def process_group(
    client: TelegramClient,
    group: str,
    text: str,
    my_id: int,
    logger: AccountLogger,
    *,
    planned_action: str = "auto",
    health_score: float = 100.0,
    speed_mode: str = "normal",
) -> OpResult:
    """
    Full per-group pipeline in one call (worker uses ONLY this).

    planned_action: auto | send | join_then_send | pre_join
    """
    if not group or not client:
        return "error"
    if planned_action == "pre_join" and not text:
        text = " "  # join-only; text unused

    if planned_action in ("join_then_send", "pre_join"):
        return await _execute_join_path(
            client,
            group,
            text,
            logger,
            send_after=planned_action == "join_then_send",
            health_score=health_score,
            speed_mode=speed_mode,
        )

    if not text:
        return "error"

    precheck = await _needs_resend(client, group, my_id, text)
    if isinstance(precheck, tuple):
        return precheck
    if not precheck:
        return "skipped"

    result = await _send(client, group, text)
    if result == "ok":
        return "sent"

    if isinstance(result, tuple):
        return result

    if result == "cant_write":
        return await _execute_join_path(
            client,
            group,
            text,
            logger,
            send_after=True,
            health_score=health_score,
            speed_mode=speed_mode,
        )

    return result
