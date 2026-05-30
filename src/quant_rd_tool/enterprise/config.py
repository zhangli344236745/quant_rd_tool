"""Enterprise module configuration (optional; default off)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from quant_rd_tool.network_settings import load_settings

_SETTINGS_PATH = "data/settings.json"


@dataclass
class EnterpriseConfig:
    enabled: bool = False
    require_auth: bool = False
    audit_enabled: bool = True
    api_keys: list[dict[str, str]] | None = None

    def valid_keys(self) -> list[str]:
        keys: list[str] = []
        for row in self.api_keys or []:
            k = str(row.get("key") or "").strip()
            if k:
                keys.append(k)
        env_keys = os.environ.get("QUANT_RD_API_KEYS", "").strip()
        if env_keys:
            keys.extend(k.strip() for k in env_keys.split(",") if k.strip())
        return keys

    def admin_password(self) -> str:
        return os.environ.get("QUANT_RD_ADMIN_PASSWORD", "").strip()


def get_enterprise_config() -> EnterpriseConfig:
    data = load_settings(_SETTINGS_PATH)
    ent = data.get("enterprise") if isinstance(data.get("enterprise"), dict) else {}

    enabled = ent.get("enabled", False) is True
    if os.environ.get("QUANT_RD_ENTERPRISE_ENABLED", "").lower() in ("1", "true", "yes"):
        enabled = True

    require_auth = ent.get("require_auth", False) is True
    audit_enabled = ent.get("audit_enabled", True) is not False
    api_keys = ent.get("api_keys") if isinstance(ent.get("api_keys"), list) else []

    return EnterpriseConfig(
        enabled=enabled,
        require_auth=require_auth and enabled,
        audit_enabled=audit_enabled if enabled else False,
        api_keys=api_keys,
    )


def enterprise_public_status() -> dict[str, Any]:
    cfg = get_enterprise_config()
    return {
        "enabled": cfg.enabled,
        "require_auth": cfg.require_auth,
        "audit_enabled": cfg.audit_enabled,
        "api_key_count": len(cfg.valid_keys()),
        "login_available": bool(cfg.admin_password()),
    }


def save_enterprise_settings(
    *,
    enabled: bool | None = None,
    require_auth: bool | None = None,
    audit_enabled: bool | None = None,
    api_keys: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    from pathlib import Path
    import json

    p = Path(_SETTINGS_PATH)
    data = load_settings(p)
    ent = dict(data.get("enterprise") or {}) if isinstance(data.get("enterprise"), dict) else {}
    if enabled is not None:
        ent["enabled"] = enabled
    if require_auth is not None:
        ent["require_auth"] = require_auth
    if audit_enabled is not None:
        ent["audit_enabled"] = audit_enabled
    if api_keys is not None:
        ent["api_keys"] = api_keys
    data["enterprise"] = ent
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return enterprise_public_status()
