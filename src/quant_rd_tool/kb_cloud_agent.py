"""Cursor Cloud Agents REST API client (v1)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from quant_rd_tool.config import settings

logger = logging.getLogger(__name__)

CURSOR_API_BASE = "https://api.cursor.com/v1"
_TERMINAL_STATUSES = frozenset({"FINISHED", "ERROR", "CANCELLED", "EXPIRED"})


def is_cloud_agent_id(agent_id: str | None) -> bool:
    """Cloud agent IDs from REST API start with ``bc-``."""
    return bool(agent_id and str(agent_id).startswith("bc-"))


class CursorCloudAgentError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class CursorCloudAgentClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = CURSOR_API_BASE,
        timeout: float = 60.0,
        proxy: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if proxy:
            client_kwargs["proxy"] = proxy
        self._client = httpx.Client(auth=(api_key, ""), **client_kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CursorCloudAgentClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._client.request(method, self._url(path), **kwargs)
        if resp.status_code >= 400:
            body: Any
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:500]
            raise CursorCloudAgentError(
                f"Cursor API {method} {path} failed: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=body,
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def me(self) -> dict[str, Any]:
        data = self._request("GET", "/me")
        return data if isinstance(data, dict) else {}

    def create_agent(
        self,
        prompt_text: str,
        *,
        model_id: str | None = None,
        name: str | None = None,
    ) -> tuple[str, str]:
        body: dict[str, Any] = {
            "prompt": {"text": prompt_text},
            "name": (name or "Finance KB")[:100],
        }
        mid = model_id or settings.kb_cursor_model
        if mid:
            body["model"] = {"id": mid}
        data = self._request("POST", "/agents", json=body)
        agent = (data or {}).get("agent") or {}
        run = (data or {}).get("run") or {}
        agent_id = agent.get("id")
        run_id = run.get("id")
        if not agent_id or not run_id:
            raise CursorCloudAgentError("create agent response missing agent/run id", body=data)
        return str(agent_id), str(run_id)

    def create_run(self, agent_id: str, prompt_text: str) -> str:
        data = self._request(
            "POST",
            f"/agents/{agent_id}/runs",
            json={"prompt": {"text": prompt_text}},
        )
        run = (data or {}).get("run") or {}
        run_id = run.get("id")
        if not run_id:
            raise CursorCloudAgentError("create run response missing run id", body=data)
        return str(run_id)

    def get_run(self, agent_id: str, run_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/agents/{agent_id}/runs/{run_id}")
        return data if isinstance(data, dict) else {}

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/agents/{agent_id}")
        return data if isinstance(data, dict) else {}

    def wait_for_run(
        self,
        agent_id: str,
        run_id: str,
        *,
        poll_interval: float = 2.0,
        timeout: float | None = None,
    ) -> str:
        deadline = time.time() + (timeout or settings.kb_cloud_agent_timeout)
        last_status = ""
        while time.time() < deadline:
            run = self.get_run(agent_id, run_id)
            status = str(run.get("status") or "").upper()
            last_status = status or last_status
            if status in _TERMINAL_STATUSES:
                if status == "FINISHED":
                    text = run.get("result") or run.get("text") or ""
                    return str(text).strip() or "(无回复)"
                raise CursorCloudAgentError(
                    f"cloud agent run ended with {status}",
                    body=run,
                )
            time.sleep(poll_interval)
        raise CursorCloudAgentError(
            f"cloud agent run timed out (last status={last_status or 'unknown'})",
        )

    def stream_run_text(self, agent_id: str, run_id: str) -> Iterator[str]:
        with self._client.stream(
            "GET",
            self._url(f"/agents/{agent_id}/runs/{run_id}/stream"),
            headers={"Accept": "text/event-stream"},
            timeout=None,
        ) as resp:
            if resp.status_code >= 400:
                content = resp.read().decode("utf-8", errors="replace")[:500]
                raise CursorCloudAgentError(
                    f"stream failed: HTTP {resp.status_code}",
                    status_code=resp.status_code,
                    body=content,
                )
            event_type: str | None = None
            buffer = ""
            for chunk in resp.iter_bytes():
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.rstrip("\r")
                    if not line:
                        event_type = None
                        continue
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if event_type == "assistant":
                        text = payload.get("text")
                        if text:
                            yield str(text)
                    elif event_type == "result":
                        text = payload.get("text")
                        if text:
                            yield str(text)
                    elif event_type == "error":
                        msg = payload.get("message") or payload.get("code") or raw
                        raise CursorCloudAgentError(f"stream error: {msg}", body=payload)


def default_client() -> CursorCloudAgentClient:
    key = settings.cursor_api_key
    if not key:
        raise CursorCloudAgentError("CURSOR_API_KEY not configured")
    proxy = settings.https_proxy or settings.http_proxy
    return CursorCloudAgentClient(
        key,
        base_url=settings.kb_cursor_api_base,
        proxy=proxy,
    )


def cloud_agent_available() -> bool:
    return bool((settings.cursor_api_key or "").strip())


def check_cursor_api() -> dict[str, Any]:
    """Live ping to Cursor REST /me (validates key + network/proxy)."""
    if not cloud_agent_available():
        return {"ok": False, "error": "CURSOR_API_KEY not configured"}
    try:
        with default_client() as client:
            me = client.me()
        return {
            "ok": True,
            "user_email": me.get("userEmail"),
            "api_key_name": me.get("apiKeyName"),
        }
    except CursorCloudAgentError as exc:
        return {"ok": False, "error": str(exc), "status_code": exc.status_code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
