"""Kill switch & webhook settings for crypto ops (persisted in data/settings.json)."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from quant_rd_tool.network_settings import load_settings, settings_json_path
from quant_rd_tool.perp_telemetry import Notifier, noop_notifier

def _read_all() -> dict[str, Any]:
    return load_settings(settings_json_path())


def _write_all(data: dict[str, Any]) -> None:
    path = settings_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_crypto_ops() -> dict[str, Any]:
    data = _read_all()
    co = data.get("crypto_ops") if isinstance(data.get("crypto_ops"), dict) else {}
    return {
        "kill_switch": bool(co.get("kill_switch", False)),
        "webhook_url": str(co.get("webhook_url") or ""),
        "webhook_on_error": co.get("webhook_on_error", True) is not False,
        "webhook_on_circuit_breaker": co.get("webhook_on_circuit_breaker", True) is not False,
        "updated_at": co.get("updated_at"),
    }


def save_crypto_ops(
    *,
    kill_switch: bool | None = None,
    webhook_url: str | None = None,
    webhook_on_error: bool | None = None,
    webhook_on_circuit_breaker: bool | None = None,
) -> dict[str, Any]:
    data = _read_all()
    co = dict(data.get("crypto_ops") or {}) if isinstance(data.get("crypto_ops"), dict) else {}
    if kill_switch is not None:
        co["kill_switch"] = kill_switch
    if webhook_url is not None:
        co["webhook_url"] = webhook_url.strip()
    if webhook_on_error is not None:
        co["webhook_on_error"] = webhook_on_error
    if webhook_on_circuit_breaker is not None:
        co["webhook_on_circuit_breaker"] = webhook_on_circuit_breaker
    co["updated_at"] = now_iso()
    data["crypto_ops"] = co
    _write_all(data)
    return get_crypto_ops()


def is_kill_switch_active() -> bool:
    return get_crypto_ops()["kill_switch"]


def post_webhook(url: str, payload: dict[str, Any], *, timeout: float = 8.0) -> None:
    if not url:
        return
    from quant_rd_tool.notification_format import format_webhook_text

    text = format_webhook_text(payload)
    body = {"text": text, "content": text, **payload}
    with httpx.Client(timeout=timeout) as client:
        client.post(url, json=body)


def _format_webhook_text(payload: dict[str, Any]) -> str:
    """Backward-compatible alias; prefer ``notification_format.format_webhook_text``."""
    from quant_rd_tool.notification_format import format_webhook_text

    return format_webhook_text(payload)


def should_notify_webhook(record: dict[str, Any], ops: dict[str, Any]) -> bool:
    url = (ops.get("webhook_url") or "").strip()
    if not url:
        return False
    decision = str(record.get("decision") or "")
    if ops.get("webhook_on_error") and (
        decision == "error" or record.get("error_category")
    ):
        return True
    if ops.get("webhook_on_circuit_breaker") and decision == "blocked_circuit_breaker":
        return True
    return False


def webhook_notifier(record: dict[str, Any]) -> None:
    ops = get_crypto_ops()
    if not should_notify_webhook(record, ops):
        return
    try:
        post_webhook(ops["webhook_url"], record)
    except Exception:
        pass


def make_telemetry_notifier() -> Notifier:
    ops = get_crypto_ops()
    if not (ops.get("webhook_url") or "").strip():
        return noop_notifier
    return webhook_notifier
