"""Mount quant_trade_tool Vue build (dist/) on the FastAPI app."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.routing import Match, Route

# src/quant_rd_tool/frontend_static.py -> src/quant_trade_tool/dist
_DEFAULT_DIST = Path(__file__).resolve().parent.parent / "quant_trade_tool" / "dist"

_SPA_EXCLUDE_PREFIXES = ("api/", "docs", "redoc", "openapi.json")
_SPA_EXCLUDE_EXACT = frozenset({"docs", "redoc", "openapi.json"})


class _SpaFallbackRoute(Route):
    """GET /* fallback for Vue history mode — must not path-match /api/* (avoids POST → 405)."""

    def matches(self, scope):  # type: ignore[no-untyped-def]
        if scope["type"] == "http" and scope.get("path", "").startswith("/api"):
            return Match.NONE, {}
        return super().matches(scope)


def resolve_frontend_dist() -> Path | None:
    override = os.environ.get("QUANT_FRONTEND_DIST", "").strip()
    dist = Path(override) if override else _DEFAULT_DIST
    if dist.is_dir() and (dist / "index.html").is_file():
        return dist
    return None


def mount_frontend(app: FastAPI) -> bool:
    """
    Serve Vue SPA from dist/. Returns True if mounted.

    - /assets/*  static files from Vite build
    - /*         index.html fallback for client-side routes
    """
    dist = resolve_frontend_dist()
    if dist is None:
        return False

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="quant-frontend-assets")

    index_path = dist / "index.html"

    _no_cache = {"Cache-Control": "no-cache"}

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        return FileResponse(index_path, headers=_no_cache)

    async def frontend_spa(request: Request) -> FileResponse:
        # Starlette Route passes Request, not path params as kwargs.
        full_path = request.path_params.get("full_path") or ""
        if full_path in _SPA_EXCLUDE_EXACT or full_path.startswith(_SPA_EXCLUDE_PREFIXES):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_path, headers=_no_cache)

    app.router.routes.append(
        _SpaFallbackRoute("/{full_path:path}", frontend_spa, methods=["GET"], name="frontend_spa"),
    )

    return True
