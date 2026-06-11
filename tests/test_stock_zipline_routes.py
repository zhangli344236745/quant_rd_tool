from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from quant_rd_tool.main import app

client = TestClient(app)


def test_stock_zipline_strategies_route():
    r = client.get("/api/v1/stocks/zipline/strategies")
    assert r.status_code == 200, r.text
    body = r.json()
    strategies = body.get("strategies", [])
    assert len(strategies) >= 2
    ids = {s["id"] for s in strategies}
    assert "ma_crossover" in ids
    assert "xgb_alpha158" in ids
    assert not any(i.startswith("opt_") for i in ids)


def test_stock_zipline_status_route():
    r = client.get("/api/v1/stocks/zipline/status?data_dir=data")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("market") == "stock"
    assert "engines" in body
    assert "pandas" in body["engines"]


def test_stock_zipline_backtest_mock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = {
        "run_id": "r1",
        "symbol": "SH600519",
        "code": "600519",
        "strategy": "ma_crossover",
        "engine": "pandas",
        "metrics": {"total_return": 0.05, "sharpe": 0.5, "max_drawdown": -0.02, "trade_count": 1},
        "trades": [],
        "equity_curve": [],
    }

    with patch("quant_rd_tool.stock_zipline_lab.run_lab_backtest", return_value=fake):
        r = client.post(
            "/api/v1/stocks/zipline/backtest",
            json={"symbol": "600519", "strategy": "ma_crossover", "start": "2024-01-01", "end": "2025-06-01"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["run_id"] == "r1"


