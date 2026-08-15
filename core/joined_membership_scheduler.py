"""Background scheduler — keep On Telegram counts fresh (5–10 min)."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Awaitable, Callable

from core.account_info_store import load_account_info
from core.config import (
    ACCOUNT_SLOTS,
    MEMBERSHIP_REFRESH_INTERVAL_SECONDS,
    MEMBERSHIP_REFRESH_STAGGER_SECONDS,
)
from core.joined_membership import is_membership_stale, refresh_membership

if TYPE_CHECKING:
    from services.account_manager import AccountManager

logger = logging.getLogger(__name__)


class JoinedMembershipScheduler:
    def __init__(
        self,
        registry: AccountManager,
        push_state: Callable[[], Awaitable[None]],
    ) -> None:
        self._registry = registry
        self._push_state = push_state
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="joined_membership_scheduler")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def schedule_stale_refresh(self, *, reason: str = "stale") -> None:
        """Fire-and-forget refresh for all stale logged-in accounts."""
        asyncio.create_task(self._refresh_stale_all(reason=reason))

    async def _refresh_stale_all(self, *, reason: str) -> None:
        for slot in ACCOUNT_SLOTS:
            if not self._running:
                return
            worker = self._registry.get_worker(slot)
            info = worker.state.account_info or load_account_info(slot)
            if not info or not info.get("phone"):
                continue
            if not is_membership_stale(info):
                continue
            asyncio.create_task(
                self._refresh_one(slot, reason=reason),
                name=f"membership_refresh_{slot}",
            )
            await asyncio.sleep(MEMBERSHIP_REFRESH_STAGGER_SECONDS)

    async def _refresh_one(self, slot: str, *, reason: str) -> None:
        try:
            worker = self._registry.get_worker(slot)
            await refresh_membership(
                slot,
                worker,
                reason=reason,
                notify=True,
                push_state=self._push_state,
            )
        except Exception as e:
            logger.warning("membership scheduler %s: %s", slot, e)

    async def _loop(self) -> None:
        await asyncio.sleep(45.0)
        while self._running:
            try:
                await self._refresh_stale_all(reason="scheduled")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("membership scheduler loop: %s", e)
            jitter = random.uniform(0, 60)
            await asyncio.sleep(MEMBERSHIP_REFRESH_INTERVAL_SECONDS + jitter)
