"""
Send message to a group — fully self-sufficient (standalone API).
Handles join-if-needed and flood retry internally. No other feature imports.
"""

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    UsernameNotOccupiedError,
    UsernameInvalidError,
    ChannelPrivateError,
    ChatRestrictedError,
)
from telethon.tl.functions.channels import JoinChannelRequest

from core.structured_logging import LogEvent
from features.delay_handler import wait_seconds
from features.logging_feature import AccountLogger


async def _join_group(client: TelegramClient, group: str, logger: AccountLogger) -> str:
    try:
        await client(JoinChannelRequest(group))
        await wait_seconds(3)
        return "ok"
    except FloodWaitError as e:
        if e.seconds > 60:
            await logger.log_event(LogEvent.FLOOD_WAIT, "warning", group=group, wait_sec=e.seconds, phase="join")
            return "flood"
        await wait_seconds(e.seconds + 5)
        try:
            await client(JoinChannelRequest(group))
            await wait_seconds(3)
            return "ok"
        except Exception:
            return "flood"
    except (ChannelPrivateError, UserBannedInChannelError):
        return "blocked"
    except ChatWriteForbiddenError:
        return "blocked"
    except Exception as e:
        err = str(e).lower()
        if "private" in err or "banned" in err:
            return "blocked"
        await logger.log_event(LogEvent.JOIN_FAIL, "error", group=group, error=str(e))
        return "error"


async def send_message(
    client: TelegramClient,
    group: str,
    text: str,
    logger: AccountLogger,
) -> str:
    """
    Send a message — self-contained.
    Returns: 'ok' | 'invalid' | 'blocked' | 'cant_write' | 'flood' | 'error'
    """
    if not group or not text or not client or not client.is_connected():
        return "error"

    try:
        await client.send_message(group, text)
        return "ok"
    except FloodWaitError as e:
        if e.seconds > 60:
            return "flood"
        await wait_seconds(e.seconds + 5)
        try:
            await client.send_message(group, text)
            return "ok"
        except Exception:
            return "flood"
    except (UsernameNotOccupiedError, UsernameInvalidError):
        return "invalid"
    except (ChannelPrivateError, UserBannedInChannelError, ChatRestrictedError):
        return "blocked"
    except ChatWriteForbiddenError:
        join_result = await _join_group(client, group, logger)
        if join_result != "ok":
            return join_result
        try:
            await client.send_message(group, text)
            return "ok"
        except FloodWaitError as e:
            if e.seconds > 60:
                return "flood"
            await wait_seconds(e.seconds + 5)
            try:
                await client.send_message(group, text)
                return "ok"
            except Exception:
                return "flood"
        except (UsernameNotOccupiedError, UsernameInvalidError):
            return "invalid"
        except (ChannelPrivateError, UserBannedInChannelError, ChatRestrictedError):
            return "blocked"
        except Exception as ex:
            await logger.log_event(LogEvent.SEND_FAIL, "error", group=group, error=str(ex))
            return "error"
    except Exception as e:
        err = str(e).lower()
        if "private" in err or "banned" in err:
            return "blocked"
        if "username" in err or "no user" in err:
            return "invalid"
        await logger.log_event(LogEvent.SEND_FAIL, "error", group=group, error=str(e))
        return "error"
