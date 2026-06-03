"""Bark push notifications (https://github.com/Finb/Bark)."""

from __future__ import annotations

from typing import Any

import httpx
from httpx import HTTPStatusError

DEFAULT_BARK_SERVER = "https://api.day.app"


def post_bark(
    device_key: str,
    *,
    title: str,
    body: str,
    server: str = DEFAULT_BARK_SERVER,
    group: str = "quant-rd",
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Send a Bark notification. Raises on HTTP or config errors."""
    key = str(device_key or "").strip()
    if not key:
        raise ValueError("bark device_key is required")

    base = str(server or DEFAULT_BARK_SERVER).strip().rstrip("/")
    url = f"{base}/{key}"
    payload = {
        "title": (title or "quant-rd")[:200],
        "body": (body or "")[:4000],
        "group": group[:50],
        "isArchive": "1",
        "level": "active",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            try:
                return resp.json()
            except Exception:
                return {"status": resp.status_code, "text": resp.text[:500]}
    except HTTPStatusError as e:
        if e.response.status_code == 400:
            raise ValueError(
                "Bark 服务器拒绝了请求，请检查 Device Key 与服务器地址是否正确"
            ) from e
        raise
