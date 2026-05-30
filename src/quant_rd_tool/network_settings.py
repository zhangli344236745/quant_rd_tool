"""Load proxy settings from data/settings.json into os.environ."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path("data/settings.json")


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path or _DEFAULT_PATH)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def apply_network_env(path: str | Path | None = None) -> dict[str, str]:
    """Apply http_proxy/https_proxy/no_proxy from settings file. Returns keys touched."""
    settings = load_settings(path)
    net = settings.get("network") if isinstance(settings.get("network"), dict) else settings
    if not isinstance(net, dict):
        net = settings
    touched: dict[str, str] = {}
    mapping = {
        "http_proxy": "HTTP_PROXY",
        "https_proxy": "HTTPS_PROXY",
        "no_proxy": "NO_PROXY",
    }
    for key, env_key in mapping.items():
        val = net.get(key)
        if val is None or val == "":
            continue
        os.environ[env_key] = str(val)
        os.environ[key.upper()] = str(val)
        touched[env_key] = str(val)
    return touched
