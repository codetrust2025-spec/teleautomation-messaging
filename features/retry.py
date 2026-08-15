"""Backward-compatible shim — use features.retry_on_failure."""

from features.retry_on_failure import retry_async

__all__ = ["retry_async"]
