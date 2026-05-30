"""Optional auth gate + audit logging."""

from __future__ import annotations

import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from quant_rd_tool.enterprise.audit import append_audit
from quant_rd_tool.enterprise.auth import resolve_principal
from quant_rd_tool.enterprise.config import get_enterprise_config

_PUBLIC_PREFIXES = (
    "/api/v1/health",
    "/api/v1/enterprise/status",
    "/api/v1/enterprise/login",
    "/docs",
    "/openapi.json",
    "/redoc",
)


def _is_public(path: str) -> bool:
    if not path.startswith("/api/v1"):
        return True
    return any(path == p or path.startswith(p + "?") for p in _PUBLIC_PREFIXES)


def _needs_auth(request: Request) -> bool:
    if _is_public(request.url.path):
        return False
    return request.method in ("POST", "PUT", "PATCH", "DELETE")


class EnterpriseMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        cfg = get_enterprise_config()
        started = time.perf_counter()
        principal: str | None = None
        status = 0
        error: str | None = None

        if cfg.enabled:
            api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            bearer = request.headers.get("Authorization")
            if not bearer:
                token = request.query_params.get("token")
                if token:
                    bearer = f"Bearer {token}"
            principal = resolve_principal(
                api_key_header=api_key,
                bearer=bearer,
            )
            if cfg.require_auth and _needs_auth(request) and not principal:
                status = 401
                resp = JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required (X-API-Key or Bearer token)"},
                )
                if cfg.audit_enabled:
                    self._log(request, principal, status, started, error="unauthorized")
                return resp

        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception as e:
            error = str(e)
            status = 500
            raise
        finally:
            if (
                cfg.enabled
                and cfg.audit_enabled
                and status
                and request.url.path.startswith("/api/v1")
            ):
                try:
                    self._log(request, principal, status, started, error=error)
                except Exception:
                    pass

    def _log(
        self,
        request: Request,
        principal: str | None,
        status: int,
        started: float,
        *,
        error: str | None = None,
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        client = request.client.host if request.client else ""
        append_audit(
            {
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query) if request.url.query else "",
                "status": status,
                "duration_ms": duration_ms,
                "principal": principal or "anonymous",
                "client_ip": client,
                "error": error,
            }
        )
