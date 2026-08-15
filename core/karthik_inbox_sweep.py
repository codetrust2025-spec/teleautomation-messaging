"""Global inbox sweep — auto-enqueue Karthik for all waiting real conversations.

Runs on a lightweight timer (no full state rebuilds). Complements live
listeners: catches stuck/unread chats that periodic sync missed or that
queued behind group workers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

_sweep_task: asyncio.Task | None = None
_running = False
_last_sweep_at: float = 0.0
_last_result: dict = {}

SWEEP_INTERVAL_SEC = float(os.getenv("KARTHIK_SWEEP_INTERVAL_SEC", "45"))
STARTUP_DELAY_SEC = float(os.getenv("KARTHIK_SWEEP_STARTUP_DELAY_SEC", "25"))
MAX_ENQUEUE_PER_SWEEP = int(os.getenv("KARTHIK_SWEEP_MAX_ENQUEUE", "10"))


def _priority_key(target: dict) -> tuple:
    age = target.get("age_sec")
    if age is None:
        return (2, 0)
    if age < 3600:
        return (0, age)
    return (1, -age)


async def sweep_pending_inbox() -> dict:
    """Scan every account inbox and enqueue AI for eligible waiting chats."""
    from core import ai_smart_reply
    from core.ai_smart_reply_store import get_config
    from services.crm_service import get_lead

    if not ai_smart_reply.is_enabled():
        return {"ok": False, "reason": "ai_disabled", "pending_found": 0, "enqueued": 0}

    cfg = get_config()
    mode = (str(cfg.get("mode") or "auto")).strip().lower()
    if mode != "auto":
        return {"ok": False, "reason": f"mode_{mode}", "pending_found": 0, "enqueued": 0}

    pending = ai_smart_reply.list_pending_inbound_targets()
    pending.sort(key=_priority_key)

    enqueued = 0
    for t in pending[: max(1, MAX_ENQUEUE_PER_SWEEP)]:
        try:
            await ai_smart_reply.maybe_schedule_ai_reply(
                t["slot"],
                int(t["user_id"]),
                message_id=t.get("message_id"),
                text=t["text"],
                lead=get_lead(t["slot"], int(t["user_id"])),
            )
            enqueued += 1
            await asyncio.sleep(0.12)
        except Exception as e:
            logger.debug("karthik_inbox_sweep skip %s %s: %s", t.get("slot"), t.get("user_id"), e)

    result = {
        "ok": True,
        "pending_found": len(pending),
        "enqueued": enqueued,
        "ts": time.time(),
    }
    if enqueued:
        logger.info(
            "karthik_inbox_sweep pending=%s enqueued=%s",
            len(pending),
            enqueued,
        )
    return result


async def _loop() -> None:
    global _last_sweep_at, _last_result
    await asyncio.sleep(STARTUP_DELAY_SEC)
    while _running:
        try:
            from core import telegram_client

            if not telegram_client.any_login_exclusive():
                _last_result = await sweep_pending_inbox()
                _last_sweep_at = time.time()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("karthik_inbox_sweep loop: %s", e)
        await asyncio.sleep(SWEEP_INTERVAL_SEC)


def start() -> None:
    global _sweep_task, _running
    if _sweep_task is not None and not _sweep_task.done():
        return
    _running = True
    _sweep_task = asyncio.create_task(_loop(), name="karthik_inbox_sweep")


async def stop() -> None:
    global _running, _sweep_task
    _running = False
    if _sweep_task is not None:
        _sweep_task.cancel()
        try:
            await _sweep_task
        except asyncio.CancelledError:
            pass
        _sweep_task = None


def status() -> dict:
    return {
        "running": _running,
        "last_sweep_at": _last_sweep_at or None,
        "last_result": dict(_last_result),
        "interval_sec": SWEEP_INTERVAL_SEC,
    }
