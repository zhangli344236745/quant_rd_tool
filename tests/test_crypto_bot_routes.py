from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from quant_rd_tool.main import app


def _ohlcv(n: int = 120, trend: float = 0.004) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 * (1 + trend) ** np.arange(n)
    return pd.DataFrame(
        {
            "timestamp": (dates.astype("int64") // 10**6).astype(int),
            "date": dates,
            "symbol": ["CRYPTO_BTC"] * n,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": np.full(n, 1e6),
        }
    )


def _client() -> TestClient:
    return TestClient(app)


def test_bot_run_dry_run_with_risk_params():
    df = _ohlcv()
    with patch("quant_rd_tool.binance_bot.cxt.fetch_ohlcv", return_value=df):
        resp = _client().post(
            "/api/v1/crypto/bot/run",
            json={"symbol": "BTC", "dry_run": True, "sizing_mode": "hybrid"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert "signal" in body


def test_scheduler_register_status_start_stop():
    client = _client()
    resp = client.post(
        "/api/v1/crypto/bot/scheduler/register",
        json={
            "kind": "spot",
            "interval_minutes": 5,
            "bot_id": "test-spot-btc",
            "spot": {"symbol": "BTC", "paper_mode": True, "dry_run": True},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["bot_id"] == "test-spot-btc"

    status = client.get("/api/v1/crypto/bot/scheduler/status").json()
    assert any(b["bot_id"] == "test-spot-btc" for b in status["bots"])

    # cleanup
    client.post("/api/v1/crypto/bot/scheduler/remove", params={"bot_id": "test-spot-btc"})


def test_scheduler_register_rejects_missing_config():
    resp = _client().post(
        "/api/v1/crypto/bot/scheduler/register",
        json={"kind": "perp", "interval_minutes": 5},
    )
    assert resp.status_code == 400


def test_scheduler_register_perp():
    client = _client()
    resp = client.post(
        "/api/v1/crypto/bot/scheduler/register",
        json={
            "kind": "perp",
            "interval_minutes": 5,
            "bot_id": "test-perp-btc",
            "perp": {"base": "BTC", "dry_run": True, "timeframe": "5m"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bot_id"] == "test-perp-btc"
    assert body["kind"] == "perp"
    client.post("/api/v1/crypto/bot/scheduler/remove", params={"bot_id": "test-perp-btc"})
