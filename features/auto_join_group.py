"""Auto-join group — standalone. Does not send messages or call other features."""

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    UserBannedInChannelError,
    ChatWriteForbiddenError,
)
from telethon.tl.functions.channels import JoinChannelRequest

from features.delay_handler import wait_seconds
from features.logging_feature import AccountLogger


async def auto_join_group(
    client: TelegramClient,
    group: str,
    logger: AccountLogger,
) -> str:
    """Returns: 'ok' | 'blocked' | 'flood' | 'error'"""
    if not group or not client or not client.is_connected():
        return "error"
    try:
        await client(JoinChannelRequest(group))
        await wait_seconds(3)
        return "ok"
    except FloodWaitError as e:
        if e.seconds > 60:
            await logger.log(f"⚠ FloodWait joining {group}: {e.seconds}s", "warning")
            return "flood"
        await wait_seconds(e.seconds + 5)
        try:
            await client(JoinChannelRequest(group))
            await wait_seconds(3)
            return "ok"
        except Exception:
            return "flood"
    except (ChannelPrivateError, UserBannedInChannelError, ChatWriteForbiddenError):
        return "blocked"
    except Exception as e:
        await logger.log(f"✗ {group}: join failed — {e}", "error")
        return "error"
