"""Delay handler — standalone timing utilities."""

import asyncio
from typing import Callable, Awaitable


async def wait_seconds(seconds: float, should_continue: Callable[[], bool] | None = None) -> None:
    if seconds <= 0:
        return
    steps = max(1, int(seconds))
    for _ in range(steps):
        if should_continue and not should_continue():
            return
        await asyncio.sleep(min(1.0, seconds))
        seconds -= 1.0


async def wait_with_countdown(
    total_seconds: int,
    should_continue: Callable[[], bool],
    on_tick: Callable[[int], None] | None = None,
) -> None:
    for remaining in range(total_seconds, 0, -1):
        if not should_continue():
            return
        if on_tick:
            on_tick(remaining)
        await asyncio.sleep(1)
