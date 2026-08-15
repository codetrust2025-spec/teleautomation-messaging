"""Retry on failure — wraps any async callable independently."""

import asyncio
from typing import TypeVar, Callable, Awaitable

T = TypeVar("T")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 2,
    delay_seconds: float = 5,
    on_fail: Callable[[Exception, int], Awaitable[None]] | None = None,
) -> T | None:
    """Execute fn up to max_attempts times. Each attempt is isolated."""
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as e:
            last_err = e
            if on_fail:
                await on_fail(e, attempt)
            if attempt < max_attempts:
                await asyncio.sleep(delay_seconds)
    if last_err:
        raise last_err
    return None
