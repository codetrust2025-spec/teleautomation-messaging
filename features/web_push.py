"""Web Push subscriptions and delivery (PWA / iPhone Home Screen)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any

from core.config import DATA_DIR

logger = logging.getLogger(__name__)

_SUBS_PATH = os.path.join(DATA_DIR, "web_push_subscriptions.json")
_VAPID_PATH = os.path.join(DATA_DIR, "vapid_keys.json")
_lock = threading.Lock()


def _load_subs() -> dict[str, Any]:
    if not os.path.isfile(_SUBS_PATH):
        return {"subscriptions": []}
    try:
        with open(_SUBS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("subscriptions"), list):
            return data
    except Exception:
        pass
    return {"subscriptions": []}


def _save_subs(data: dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = _SUBS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _SUBS_PATH)


def _load_vapid_file() -> dict[str, str] | None:
    if not os.path.isfile(_VAPID_PATH):
        return None
    try:
        with open(_VAPID_PATH, encoding="utf-8") as f:
            data = json.load(f)
        pub = str(data.get("public_key") or "").strip()
        priv = str(data.get("private_key") or "").strip()
        if pub and priv:
            return {"public_key": pub, "private_key": priv}
    except Exception:
        pass
    return None


def _save_vapid_file(keys: dict[str, str]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = _VAPID_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(keys, f, indent=2)
    os.replace(tmp, _VAPID_PATH)


def _generate_vapid_keys() -> dict[str, str]:
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    vapid = Vapid02()
    vapid.generate_keys()
    raw = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_key = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    private_key = vapid.private_pem().decode("utf-8")
    return {"public_key": public_key, "private_key": private_key}


def vapid_keys() -> dict[str, str] | None:
    """Return {public_key, private_key} (base64url) or None if unavailable."""
    env_pub = (os.environ.get("WEB_PUSH_VAPID_PUBLIC_KEY") or "").strip()
    env_priv = (os.environ.get("WEB_PUSH_VAPID_PRIVATE_KEY") or "").strip()
    if env_pub and env_priv:
        return {"public_key": env_pub, "private_key": env_priv}
    with _lock:
        cached = _load_vapid_file()
        if cached:
            return cached
        try:
            generated = _generate_vapid_keys()
            _save_vapid_file(generated)
            return generated
        except Exception as e:
            logger.warning("web_push: could not generate VAPID keys: %s", e)
            return None


def public_vapid_key() -> str | None:
    keys = vapid_keys()
    return keys["public_key"] if keys else None


def vapid_claims_email() -> str:
    return (os.environ.get("WEB_PUSH_VAPID_EMAIL") or "mailto:admin@example.invalid").strip()


def register_subscription(
    *,
    username: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    user = (username or "").strip()
    ep = (endpoint or "").strip()
    dh = (p256dh or "").strip()
    au = (auth or "").strip()
    op_role = (role or "admin").strip().lower() or "admin"
    if not user or not ep or not dh or not au:
        raise ValueError("username, endpoint, p256dh, and auth required")
    with _lock:
        data = _load_subs()
        rows = data.setdefault("subscriptions", [])
        now = time.time()
        updated = False
        for row in rows:
            if row.get("endpoint") == ep:
                row.update(
                    {
                        "username": user,
                        "role": op_role,
                        "p256dh": dh,
                        "auth": au,
                        "user_agent": user_agent,
                        "updated_at": now,
                    }
                )
                updated = True
                break
        if not updated:
            rows.append(
                {
                    "username": user,
                    "role": op_role,
                    "endpoint": ep,
                    "p256dh": dh,
                    "auth": au,
                    "user_agent": user_agent,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        _save_subs(data)
        return {"username": user, "registered": True}


def unregister_subscription(*, username: str, endpoint: str) -> int:
    user = (username or "").strip()
    ep = (endpoint or "").strip()
    if not user or not ep:
        return 0
    with _lock:
        data = _load_subs()
        before = len(data.get("subscriptions") or [])
        data["subscriptions"] = [
            r
            for r in (data.get("subscriptions") or [])
            if not (r.get("username") == user and r.get("endpoint") == ep)
        ]
        removed = before - len(data["subscriptions"])
        if removed:
            _save_subs(data)
        return removed


def subscriptions_for_user(username: str, *, role: str | None = None) -> list[dict[str, Any]]:
    user = (username or "").strip()
    if not user:
        return []
    want_role = (role or "").strip().lower() or None
    data = _load_subs()
    rows = [
        r
        for r in (data.get("subscriptions") or [])
        if r.get("username") == user and r.get("endpoint")
    ]
    if want_role:
        rows = [r for r in rows if (r.get("role") or "admin").lower() == want_role]
    return rows


def all_usernames_with_subscriptions() -> list[str]:
    data = _load_subs()
    users = {r.get("username") for r in (data.get("subscriptions") or []) if r.get("username")}
    return sorted(users)


def admin_usernames_with_subscriptions() -> list[str]:
    data = _load_subs()
    return sorted({r.get("username") for r in (data.get("subscriptions") or []) if r.get("username") and (r.get("role") or "admin").lower() == "admin"})


def status() -> dict[str, Any]:
    keys = vapid_keys()
    data = _load_subs()
    rows = data.get("subscriptions") or []
    users = {r.get("username") for r in rows if r.get("username")}
    return {
        "configured": bool(keys),
        "total_subscriptions": len(rows),
        "users": len(users),
    }


def _send_one(sub: dict[str, Any], payload: dict[str, Any], *, private_key: str) -> bool:
    from pywebpush import WebPushException, webpush

    subscription_info = {
        "endpoint": sub["endpoint"],
        "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload, separators=(",", ":")),
            vapid_private_key=private_key,
            vapid_claims={"sub": vapid_claims_email()},
        )
        return True
    except WebPushException as e:
        status_code = getattr(e.response, "status_code", None) if e.response else None
        if status_code in (404, 410):
            unregister_subscription(username=sub.get("username") or "", endpoint=sub["endpoint"])
        logger.debug("web_push send failed (%s): %s", status_code, e)
        return False
    except Exception as e:
        logger.debug("web_push send error: %s", e)
        return False


def send_to_user(
    username: str,
    *,
    title: str,
    body: str,
    slot: str | None = None,
    user_id: int | str | None = None,
    tag: str | None = None,
) -> int:
    """Send push to all subscriptions for username. Returns success count."""
    keys = vapid_keys()
    if not keys:
        return 0
    subs = subscriptions_for_user(username)
    if not subs:
        return 0
    url = "/"
    if slot and user_id is not None:
        url = f"/?open_chat=1&slot={slot}&user_id={user_id}"
    payload = {
        "title": title,
        "body": body,
        "url": url,
        "slot": slot,
        "user_id": str(user_id) if user_id is not None else None,
        "tag": tag or (f"inbox:{slot}:{user_id}" if slot and user_id is not None else "inbox"),
    }
    ok = 0
    for sub in subs:
        if _send_one(sub, payload, private_key=keys["private_key"]):
            ok += 1
    return ok


async def notify_new_inbound_message(
    *,
    slot: str,
    user_id: int,
    name: str | None,
    username: str | None,
    text: str,
) -> None:
    """Fire-and-forget push to all subscribed devices (phone + PWA)."""
    keys = vapid_keys()
    if not keys:
        return
    users = all_usernames_with_subscriptions()
    if not users:
        return
    label = (name or username or f"User {user_id}").strip()
    preview = (text or "New message").replace("\n", " ").strip()
    if len(preview) > 120:
        preview = preview[:117] + "…"
    title = f"New message — {label}"
    body = preview or "Tap to open chat"

    def _run() -> None:
        for user in users:
            send_to_user(
                user,
                title=title,
                body=body,
                slot=slot,
                user_id=user_id,
                tag=f"inbox:{slot}:{user_id}",
            )

    await asyncio.to_thread(_run)
