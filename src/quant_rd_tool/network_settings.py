"""Load proxy settings from data/settings.json into os.environ."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


def settings_json_path() -> Path:
    """Repo-root ``data/settings.json`` (independent of process cwd)."""
    from quant_rd_tool.config import _project_root

    return _project_root() / "data" / "settings.json"


def _legacy_settings_paths() -> list[Path]:
    from quant_rd_tool.config import _project_root

    root = _project_root()
    return [
        root / "src" / "quant_trade_tool" / "data" / "settings.json",
        Path("data/settings.json"),
    ]


def _migrate_legacy_settings(target: Path) -> bool:
    if target.is_file():
        return False
    for legacy in _legacy_settings_paths():
        if legacy.is_file() and legacy.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, target)
            return True
    return False


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else settings_json_path()
    if not path:
        _migrate_legacy_settings(p)
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
