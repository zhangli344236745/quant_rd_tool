from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from quant_rd_tool.main import app

client = TestClient(app)

FAKE_SYMBOL = {
    "symbol": "BTC",
    "method": "historical_simulation",
    "params": {"timeframe": "4h", "lookback_bars": 360, "horizon_bars": 1},
    "notional_usdt": 10_000,
    "latest_price": 100_000,
    "observations": 300,
    "metrics": {"0.99": {"var_pct": 0.04, "var_usdt": 400, "cvar_usdt": 520}},
    "narrative": {"headline": "test", "bullets": [], "disclaimer": "test"},
}

FAKE_BREACH = {
    "symbol": "BTC",
    "timeframe": "4h",
    "confidence": 0.99,
    "actual_return": -0.06,
    "var_pct": 0.04,
    "var_usdt": 400,
    "breached": True,
    "severity": "warning",
}

FAKE_PORTFOLIO_BREACH = {
    "enabled": True,
    "timeframe": "4h",
    "breached": False,
    "var_pct": 0.05,
    "var_usdt": 500,
}


def test_var_symbol_route():
    with patch("quant_rd_tool.crypto_var.build_symbol_var_report", return_value=FAKE_SYMBOL):
        r = client.get("/api/v1/crypto/var/symbol?symbol=BTC&timeframe=4h&horizon_bars=1")
    assert r.status_code == 200, r.text
    assert r.json()["params"]["timeframe"] == "4h"


def test_var_symbol_breach_route():
    with patch("quant_rd_tool.crypto_var.build_symbol_var_breach", return_value=FAKE_BREACH):
        r = client.get("/api/v1/crypto/var/symbol/breach?symbol=BTC&timeframe=4h")
    assert r.status_code == 200, r.text
    assert r.json()["breached"] is True


def test_var_portfolio_breach_route():
    with patch("quant_rd_tool.crypto_var.build_portfolio_var_breach", return_value=FAKE_PORTFOLIO_BREACH):
        r = client.get("/api/v1/crypto/var/portfolio/breach?timeframe=4h")
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
