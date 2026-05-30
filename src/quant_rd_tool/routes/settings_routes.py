"""Workbench settings (proxy, export/import)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_rd_tool.network_settings import apply_network_env, load_settings
from quant_rd_tool.watchlist import Watchlist

router = APIRouter()

_SETTINGS_PATH = Path("data/settings.json")


class NetworkSettings(BaseModel):
    http_proxy: str = ""
    https_proxy: str = ""
    no_proxy: str = ""


def _read_all() -> dict[str, Any]:
    return load_settings(_SETTINGS_PATH)


def _write_all(data: dict[str, Any]) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/network")
def get_network() -> dict[str, Any]:
    data = _read_all()
    net = data.get("network") if isinstance(data.get("network"), dict) else {}
    return {
        "http_proxy": net.get("http_proxy", ""),
        "https_proxy": net.get("https_proxy", ""),
        "no_proxy": net.get("no_proxy", ""),
    }


@router.post("/network")
def save_network(req: NetworkSettings) -> dict[str, Any]:
    data = _read_all()
    data["network"] = req.model_dump()
    _write_all(data)
    apply_network_env(_SETTINGS_PATH)
    return req.model_dump()


@router.get("/export")
def export_bundle() -> dict[str, Any]:
    return {
        "settings": _read_all(),
        "watchlist": Watchlist().list_items(),
    }


class ImportBundle(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    watchlist: list[dict[str, str]] = Field(default_factory=list)


@router.post("/import")
def import_bundle(req: ImportBundle) -> dict[str, str]:
    if req.settings:
        _write_all(req.settings)
        apply_network_env(_SETTINGS_PATH)
    wl = Watchlist()
    for item in req.watchlist:
        code = str(item.get("code") or "").strip()
        if code:
            wl.add(code, name=str(item.get("name") or ""))
    return {"status": "ok"}
