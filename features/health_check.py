"""Account health / flood-ban check — runs alone, no other feature required."""



from telethon import TelegramClient

from telethon.errors import FloodWaitError



from features.logging_feature import AccountLogger



HealthResult = str | tuple[str, int]





async def check_account_health(

    client: TelegramClient,

    logger: AccountLogger,

) -> HealthResult:

    """

    Returns:

      'ok' | 'not_authorized' | 'error'

      ('flood_banned', seconds) when Telegram returns FloodWait

    """

    try:

        if not client.is_connected():

            return "error"

        if not await client.is_user_authorized():

            return "not_authorized"

        # Lightweight API ping (get_messages("telegram") fails with ChannelInvalidError on some accounts)
        await client.get_me()

        return "ok"

    except FloodWaitError as e:

        return ("flood_banned", int(e.seconds))

    except Exception as e:

        await logger.log(
            f"Health check error: {type(e).__name__}: {e}",
            "warning",
        )

        return "error"
