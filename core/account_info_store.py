"""Persist logged-in account display info across server reloads."""

from __future__ import annotations

import json
import os
import re

from core.config import ACCOUNTS, STATE_DIR


def _path(slot: str) -> str:
    return os.path.join(STATE_DIR, slot, "account_info.json")


def normalize_phone_digits(phone: str) -> str:
    """Compare phones regardless of + prefix or spacing."""
    return "".join(c for c in str(phone or "") if c.isdigit())


def slot_display_label(slot: str) -> str:
    m = re.match(r"^account(\d+)$", str(slot), re.I)
    return f"Account {m.group(1)}" if m else str(slot)


def find_logged_in_slot_by_phone(
    phone: str,
    *,
    exclude_slot: str | None = None,
) -> tuple[str, dict] | None:
    """Return (slot, account_info) if another slot already has this phone logged in."""
    key = normalize_phone_digits(phone)
    if not key:
        return None
    from core.config import ACCOUNT_SLOTS

    for slot in ACCOUNT_SLOTS:
        if exclude_slot and slot == exclude_slot:
            continue
        info = load_account_info(slot)
        if not info:
            continue
        if normalize_phone_digits(info.get("phone")) == key:
            return slot, info
    return None


def duplicate_phone_login_message(existing_slot: str, info: dict) -> str:
    label = slot_display_label(existing_slot)
    name = (info.get("display_name") or info.get("name") or "").strip()
    extra = f" — {name}" if name else ""
    return (
        f"This number is already logged in on {label}{extra}. "
        f"Use that card, or log out there before logging in here."
    )


def build_info_from_me(me, cached: dict | None = None) -> dict:
    """Build account_info from Telethon User (name, username, phone)."""
    first = (getattr(me, "first_name", None) or "").strip()
    last = (getattr(me, "last_name", None) or "").strip()
    username = (getattr(me, "username", None) or "").strip()
    name = " ".join(p for p in (first, last) if p).strip() or first
    info = {
        "name": name,
        "first_name": first,
        "last_name": last,
        "username": username,
        "phone": str(getattr(me, "phone", None) or ""),
        "telegram_premium": bool(getattr(me, "premium", False)),
    }
    if cached:
        for key in (
            "joined_groups",
            "joined_channels",
            "joined_total",
            "joined_updated_at",
            "last_join_at",
        ):
            if key in cached:
                info[key] = cached[key]
    return info


def _normalize(data: dict) -> dict:
    """Standard account_info shape for API + UI."""
    first = str(data.get("first_name") or "").strip()
    last = str(data.get("last_name") or "").strip()
    username = str(data.get("username") or "").strip().lstrip("@")
    name = str(data.get("name") or "").strip()
    if not name and (first or last):
        name = " ".join(p for p in (first, last) if p).strip()
    out = {
        "name": name,
        "first_name": first,
        "last_name": last,
        "username": username,
        "phone": str(data.get("phone") or ""),
    }
    if not out["phone"]:
        return {}
    for key in ("joined_groups", "joined_channels", "joined_total"):
        if key in data and data[key] is not None:
            try:
                out[key] = int(data[key])
            except (TypeError, ValueError):
                out[key] = 0
    if data.get("joined_updated_at"):
        out["joined_updated_at"] = str(data["joined_updated_at"])
    if data.get("last_join_at"):
        out["last_join_at"] = str(data["last_join_at"])
    if "telegram_premium" in data:
        out["telegram_premium"] = bool(data.get("telegram_premium"))
    if "is_subscription" in data:
        out["is_subscription"] = bool(data.get("is_subscription"))
    display_name = str(data.get("display_name") or "").strip()
    if display_name:
        out["display_name"] = display_name[:48]
    return out


def load_account_info(slot: str) -> dict | None:
    if slot not in ACCOUNTS:
        return None
    path = _path(slot)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            from core.subscription_accounts import enrich_account_info

            normalized = enrich_account_info(slot, _normalize(data))
            return normalized if normalized.get("phone") else None
    except Exception:
        pass
    return None


def _invalidate_partition_cache() -> None:
    """Login/logout changes the active-slot partition — refresh slice caches."""
    try:
        from core.groups_cache import invalidate_master_cache

        invalidate_master_cache()
    except Exception:
        pass


def save_account_info(slot: str, info: dict) -> None:
    if slot not in ACCOUNTS:
        return
    path = _path(slot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = load_account_info(slot) or {}
    merged = {**existing, **info}
    payload = _normalize(merged)
    if not payload:
        return
    is_new = not os.path.exists(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    if is_new:
        _invalidate_partition_cache()


def clear_account_info(slot: str) -> None:
    path = _path(slot)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
        _invalidate_partition_cache()
