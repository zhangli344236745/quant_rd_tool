"""Enterprise MVP: status, login, audit (optional module)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from quant_rd_tool.enterprise.audit import tail_audit
from quant_rd_tool.enterprise.auth import login_with_password, resolve_principal
from quant_rd_tool.enterprise.config import (
    enterprise_public_status,
    get_enterprise_config,
    save_enterprise_settings,
)

from pydantic import BaseModel, Field

router = APIRouter()


class LoginBody(BaseModel):
    password: str = Field(..., min_length=1)


class EnterpriseSettingsBody(BaseModel):
    enabled: bool | None = None
    require_auth: bool | None = None
    audit_enabled: bool | None = None
    api_keys: list[dict[str, str]] | None = None


def _require_principal(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None),
    api_key: str | None = Query(None, description="EventSource 等无法带 Header 时用"),
    token: str | None = Query(None, description="登录 token，等价于 Bearer"),
) -> str:
    cfg = get_enterprise_config()
    key = x_api_key or api_key
    bearer = authorization
    if not bearer and token:
        bearer = f"Bearer {token}"
    if not cfg.enabled or not cfg.require_auth:
        return resolve_principal(api_key_header=key, bearer=bearer) or "anonymous"
    principal = resolve_principal(api_key_header=key, bearer=bearer)
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


@router.get("/status")
def enterprise_status() -> dict[str, Any]:
    return enterprise_public_status()


@router.post("/login")
def enterprise_login(body: LoginBody) -> dict[str, Any]:
    cfg = get_enterprise_config()
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail="Enterprise module is disabled")
    out = login_with_password(body.password)
    if not out:
        raise HTTPException(status_code=401, detail="Invalid password or login not configured")
    return out


@router.get("/audit")
def enterprise_audit(
    limit: int = Query(50, ge=1, le=500),
    principal: str | None = Query(None),
    _: str = Depends(_require_principal),
) -> dict[str, Any]:
    cfg = get_enterprise_config()
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail="Enterprise module is disabled")
    items = tail_audit(limit=limit, principal=principal)
    return {"count": len(items), "items": items}


@router.get("/settings")
def enterprise_settings_get() -> dict[str, Any]:
    return enterprise_public_status()


@router.post("/settings")
def enterprise_settings_save(
    body: EnterpriseSettingsBody,
    principal: str = Depends(_require_principal),
) -> dict[str, Any]:
    if principal == "anonymous" and get_enterprise_config().require_auth:
        raise HTTPException(status_code=401, detail="Authentication required")
    return save_enterprise_settings(
        enabled=body.enabled,
        require_auth=body.require_auth,
        audit_enabled=body.audit_enabled,
        api_keys=body.api_keys,
    )
