"""
Check whether our message is last in a group.
Standalone — does not call send, join, delay, or other features.
"""

from telethon import TelegramClient

from core.structured_logging import LogEvent
from features.logging_feature import AccountLogger


async def check_last_message(
    client: TelegramClient,
    group: str,
    my_id: int,
    logger: AccountLogger,
) -> bool:
    """
    Returns True if a forward/send is needed (our message is NOT last).
    On scan failure, returns True (assume resend needed).
    """
    if not group or not client:
        return False
    try:
        messages = await client.get_messages(group, limit=1)
        if not messages:
            return True
        sender_id = getattr(messages[0], "sender_id", None) or getattr(
            messages[0], "from_id", None
        )
        if sender_id != my_id:
            return True
        await logger.log_event(LogEvent.SKIP, "info", group=group, reason="already_last")
        return False
    except Exception:
        return True
