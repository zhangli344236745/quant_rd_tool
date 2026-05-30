"""API key and short-lived login tokens."""

from __future__ import annotations

import secrets
import time
from typing import Any

from quant_rd_tool.enterprise.config import get_enterprise_config

# token -> {principal, expires_at}
_SESSIONS: dict[str, dict[str, Any]] = {}
_TOKEN_TTL_SEC = 86400


def verify_api_key(key: str | None) -> str | None:
    if not key:
        return None
    cfg = get_enterprise_config()
    for valid in cfg.valid_keys():
        if secrets.compare_digest(key, valid):
            return "api_key"
    for row in cfg.api_keys or []:
        valid = str(row.get("key") or "")
        if valid and secrets.compare_digest(key, valid):
            return str(row.get("id") or row.get("label") or "api_key")
    return None


def resolve_principal(
    *,
    api_key_header: str | None,
    bearer: str | None,
) -> str | None:
    if api_key_header:
        pid = verify_api_key(api_key_header.strip())
        if pid:
            return pid
    if bearer and bearer.lower().startswith("bearer "):
        token = bearer[7:].strip()
        sess = _SESSIONS.get(token)
        if sess and sess.get("expires_at", 0) > time.time():
            return str(sess.get("principal") or "admin")
    return None


def login_with_password(password: str) -> dict[str, Any] | None:
    cfg = get_enterprise_config()
    admin = cfg.admin_password()
    if not admin:
        return None
    if not secrets.compare_digest(password, admin):
        return None
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {"principal": "admin", "expires_at": time.time() + _TOKEN_TTL_SEC}
    return {"token": token, "expires_in": _TOKEN_TTL_SEC, "principal": "admin"}


def clear_sessions_for_tests() -> None:
    _SESSIONS.clear()
