"""Load approved WhatsApp template definitions."""

from __future__ import annotations

import os
from functools import lru_cache

import yaml

from core.config import BASE_DIR

_TEMPLATES_PATH = os.path.join(BASE_DIR, "config", "whatsapp_templates.yaml")


@lru_cache(maxsize=1)
def load_templates() -> dict[str, dict]:
    if not os.path.isfile(_TEMPLATES_PATH):
        return {}
    try:
        with open(_TEMPLATES_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except OSError:
        return {}
    out: dict[str, dict] = {}
    for key, val in raw.items():
        if key == "version" or not isinstance(val, dict):
            continue
        out[str(key)] = dict(val)
    return out


def get_template(name: str) -> dict | None:
    tpl = load_templates().get(name)
    return dict(tpl) if tpl else None


def list_template_names() -> list[str]:
    return sorted(load_templates().keys())
