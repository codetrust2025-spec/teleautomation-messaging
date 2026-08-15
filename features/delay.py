"""Backward-compatible shim — use features.delay_handler."""

from features.delay_handler import wait_seconds, wait_with_countdown

__all__ = ["wait_seconds", "wait_with_countdown"]
