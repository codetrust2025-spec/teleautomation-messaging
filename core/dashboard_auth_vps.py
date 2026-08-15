"""Dashboard operator login (separate from Telegram /login OTP).

Enable by setting DASHBOARD_PASSWORD in the environment or .env file.
When unset, auth is disabled (local dev convenience).

Env:
  DASHBOARD_USERNAME   default: admin
  DASHBOARD_PASSWORD   required to enable auth
  DASHBOARD_AUTH_SECRET optional HMAC secret (defaults to password)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

SESSION_COOKIE = "ta_session"
SESSION_TTL_SEC = 7 * 24 * 3600

_PUBLIC_EXACT = frozenset({
    "/auth/login",
    "/auth/verify-admin",
    "/auth/status",
    "/health",
    "/favicon.svg",
    "/icons.svg",
    "/sw.js",
    "/webhooks/whatsapp",
    "/push/vapid-public-key",
})

_PUBLIC_PREFIXES = (
    "/assets/",
    "/call/join/",
    "/public/",
)

# First path segment for API routes (must stay in sync with server.py serve_spa).
_API_ROOTS = frozenset({
    "groups", "account", "accounts", "login", "auth", "message", "start", "stop",
    "state", "health", "ws", "inbox", "crm", "stats", "admin", "ai", "public",
    "metrics", "alerts", "voice",
    "webhooks", "whatsapp", "push", "devices", "demo-tools", "workspace", "fleet", "api",
})


def _refresh_dashboard_env_from_file() -> None:
    """Re-read DASHBOARD_* from .env (uvicorn reload workers may skip dotenv)."""
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.normpath(os.path.join(here, "..", ".env"))
    try:
        if not os.path.isfile(env_path):
            return
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key.startswith("DASHBOARD_"):
                    os.environ[key] = value
    except OSError:
        pass


def auth_enabled() -> bool:
    _refresh_dashboard_env_from_file()
    return bool(os.environ.get("DASHBOARD_PASSWORD", "").strip())


def get_credentials() -> tuple[str, str]:
    _refresh_dashboard_env_from_file()
    username = (os.environ.get("DASHBOARD_USERNAME") or "admin").strip() or "admin"
    password = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    return username, password


def change_operator_password(username: str, current_password: str, new_password: str) -> str | None:
    user = str(username or "").strip()
    cur = str(current_password or "")
    new = str(new_password or "").strip()
    if not user or not cur or len(new) < 4:
        return "Enter current password and a new password of at least 4 characters"
    profile = resolve_operator_login(user, cur)
    if not profile:
        return "Current password is incorrect"
    expected_user, expected_pass = get_credentials()
    if not secrets.compare_digest(user, expected_user) or not secrets.compare_digest(cur, expected_pass):
        return "Current password is incorrect"
    os.environ["DASHBOARD_PASSWORD"] = new
    _refresh_dashboard_env_from_file()
    env_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    if os.path.isfile(env_path):
        try:
            lines: list[str] = []
            replaced = False
            with open(env_path, encoding="utf-8") as f:
                for raw in f:
                    if raw.strip().startswith("DASHBOARD_PASSWORD="):
                        lines.append(f"DASHBOARD_PASSWORD={new}\n")
                        replaced = True
                    else:
                        lines.append(raw)
            if not replaced:
                lines.append(f"DASHBOARD_PASSWORD={new}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except OSError:
            pass
    return None


def resolve_operator_login(username: str, password: str) -> dict[str, Any] | None:
    """Return operator profile on success: {username, role, reference}."""
    if not auth_enabled():
        return {"username": "dev", "role": "admin", "reference": None}
    user = str(username or "").strip()
    pwd = str(password or "")
    if not user or not pwd:
        return None
    expected_user, expected_pass = get_credentials()
    if (
        expected_pass
        and secrets.compare_digest(user, expected_user)
        and secrets.compare_digest(pwd, expected_pass)
    ):
        return {"username": expected_user, "role": "admin", "reference": None}
    return None


def verify_credentials(username: str, password: str) -> bool:
    return resolve_operator_login(username, password) is not None


def _secret() -> bytes:
    _refresh_dashboard_env_from_file()
    raw = (
        os.environ.get("DASHBOARD_AUTH_SECRET")
        or os.environ.get("DASHBOARD_PASSWORD")
        or "teleautomation-dev-insecure"
    )
    return raw.encode("utf-8")


def create_session_token(
    username: str,
    *,
    role: str = "admin",
    reference: str | None = None,
) -> str:
    payload = {
        "u": username,
        "exp": int(time.time()) + SESSION_TTL_SEC,
        "role": role,
        "ref": reference or "",
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_secret(), raw, hashlib.sha256).digest()
    return f"{urlsafe_b64encode(raw).decode()}.{urlsafe_b64encode(sig).decode()}"


def parse_session_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    if not auth_enabled():
        return {"username": "dev", "role": "admin", "reference": None}
    try:
        raw_part, sig_part = token.split(".", 1)
        raw = urlsafe_b64decode(raw_part.encode("utf-8"))
        sig = urlsafe_b64decode(sig_part.encode("utf-8"))
        expected = hmac.new(_secret(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(raw.decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        user = str(payload.get("u") or "").strip()
        if not user:
            return None
        if str(payload.get("role") or "admin").strip() != "admin":
            return None
        return {"username": user, "role": "admin", "reference": None}
    except Exception:
        return None


def validate_session_token(token: str | None) -> str | None:
    profile = parse_session_token(token)
    return profile.get("username") if profile else None


def operator_profile_from_cookies(cookies: dict) -> dict[str, Any]:
    if not auth_enabled():
        return {"username": "dev", "role": "admin", "reference": None}
    profile = parse_session_token(cookies.get(SESSION_COOKIE))
    if not profile:
        return {"username": None, "role": None, "reference": None}
    return profile


def is_admin_profile(profile: dict[str, Any] | None) -> bool:
    return bool((profile or {}).get("username")) and (profile or {}).get("role") == "admin"


def scoped_reference(profile: dict[str, Any] | None) -> str | None:
    """Optional reference filter from query params only (no forced handler scope)."""
    return None


def is_public_path(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def is_spa_shell_request(method: str, path: str) -> bool:
    """Allow unauthenticated GET/HEAD for the React shell (login UI is client-side)."""
    if method not in ("GET", "HEAD"):
        return False
    if is_public_path(path):
        return True
    stripped = path.strip("/")
    if not stripped:
        return True
    first = stripped.split("/")[0]
    return first not in _API_ROOTS


def username_from_request_cookies(cookies: dict) -> str | None:
    if not auth_enabled():
        return "dev"
    return validate_session_token(cookies.get(SESSION_COOKIE))
