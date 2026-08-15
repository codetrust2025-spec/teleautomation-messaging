"""Backward-compatible shim — use features.auto_join_group."""

from features.auto_join_group import auto_join_group as join_group

__all__ = ["join_group"]
