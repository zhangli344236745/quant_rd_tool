from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_rd_tool.main import app
from quant_rd_tool.stock_var import (
    build_portfolio_var_report,
    build_symbol_var_report,
    normalize_holdings,
)

client = TestClient(app)


def _fake_ohlcv_df(*_args, **_kwargs) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    close = pd.Series(100 * (1 + np.random.default_rng(1).normal(0, 0.01, 120)).cumprod(), index=dates)
    return pd.DataFrame({"date": dates, "close": close, "symbol": "SH600519"})


def test_build_symbol_var_report(monkeypatch):
    from quant_rd_tool import stock_var as sv

    monkeypatch.setattr(sv, "fetch_ohlcv_df", _fake_ohlcv_df)

    report = build_symbol_var_report(
        symbol="600519",
        notional_cny=100_000,
        lookback_bars=90,
        confidence_levels=[0.95, 0.99],
    )
    assert report["symbol"] == "SH600519"
    assert report["market"] == "stock"
    assert "0.95" in report["metrics"]
    assert report["metrics"]["0.95"]["var_cny"] > 0
    assert report["metrics"]["0.95"]["monte_carlo"]
    assert report["stress_scenarios"][0]["loss_cny"] > 0
    assert report["narrative"]["headline"]


def test_build_symbol_var_report_default_notional(monkeypatch):
    from quant_rd_tool import stock_var as sv

    dates = pd.date_range("2024-01-01", periods=80, freq="B")
    close = pd.Series(np.linspace(50, 80, 80), index=dates)
    df = pd.DataFrame({"date": dates, "close": close, "symbol": "SH600519"})
    monkeypatch.setattr(sv, "fetch_ohlcv_df", lambda *_a, **_kw: df)

    report = build_symbol_var_report(
        symbol="600519",
        notional_cny=0,
        lookback_bars=60,
        confidence_levels=[0.95],
    )
    assert report["notional_cny"] == pytest.approx(8000.0)


def test_build_portfolio_var_report(monkeypatch):
    from quant_rd_tool import stock_var as sv

    monkeypatch.setattr(sv, "fetch_ohlcv_df", _fake_ohlcv_df)
    monkeypatch.setattr(sv, "_latest_price_for_code", lambda *a, **k: 100.0)

    report = build_portfolio_var_report(
        [
            {"symbol": "600519", "notional_cny": 100_000},
            {"symbol": "000001", "notional_cny": 50_000},
        ],
        lookback_bars=60,
        confidence_levels=[0.95],
    )
    assert report["enabled"]
    assert len(report["positions"]) == 2
    assert report["metrics"]["0.95"]["var_cny"] > 0
    assert report.get("correlation")


def test_normalize_holdings_from_shares(monkeypatch):
    from quant_rd_tool import stock_var as sv

    monkeypatch.setattr(sv, "_latest_price_for_code", lambda *a, **k: 10.0)
    rows = normalize_holdings([{"symbol": "600519", "shares": 100}])
    assert rows[0]["notional_cny"] == pytest.approx(1000.0)


def test_stock_var_symbol_route(monkeypatch):
    from quant_rd_tool import stock_var as sv

    monkeypatch.setattr(sv, "fetch_ohlcv_df", _fake_ohlcv_df)
    r = client.get("/api/v1/stocks/var/symbol?symbol=600519&notional_cny=50000")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "SH600519"
    assert "metrics" in body


def test_stock_var_portfolio_route(monkeypatch):
    from quant_rd_tool import stock_var as sv

    monkeypatch.setattr(sv, "fetch_ohlcv_df", _fake_ohlcv_df)
    monkeypatch.setattr(sv, "_latest_price_for_code", lambda *a, **k: 100.0)
    r = client.post(
        "/api/v1/stocks/var/portfolio",
        json={"holdings": [{"symbol": "600519", "notional_cny": 100000}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
