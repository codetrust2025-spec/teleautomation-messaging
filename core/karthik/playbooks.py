"""Stable playbook interface; the base smart-reply module owns implementation."""

from __future__ import annotations


def apply_to_ai_module(namespace: dict) -> None:
    """Validate the extension point without replacing the audited base behavior."""
    required = ("generate_and_send",)
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"smart-reply extension point missing: {', '.join(missing)}")


def get_ops_playbook() -> str:
    return "Keep replies concise, do not invent facts, preserve thread intent, and require human approval for consequential actions."


def meta() -> dict:
    return {"name": "messaging-safe-base", "version": 1, "overrides": []}
