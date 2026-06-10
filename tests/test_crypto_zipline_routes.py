from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from quant_rd_tool.main import app

client = TestClient(app)


def test_zipline_strategies_route():
    r = client.get("/api/v1/crypto/zipline/strategies")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body.get("strategies", [])) >= 53


def test_zipline_status_route():
    r = client.get("/api/v1/crypto/zipline/status?data_dir=data")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "engines" in body
    assert "pandas" in body["engines"]


def test_zipline_backtest_mock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = {
        "run_id": "r1",
        "symbol": "BTC",
        "strategy": "ma_crossover",
        "engine": "pandas",
        "metrics": {"total_return": 0.05, "sharpe": 0.5, "max_drawdown": -0.02, "trade_count": 1},
        "trades": [],
        "equity_curve": [],
    }

    with patch("quant_rd_tool.crypto_zipline_lab.run_lab_backtest", return_value=fake):
        r = client.post(
            "/api/v1/crypto/zipline/backtest",
            json={"symbol": "BTC", "strategy": "ma_crossover", "start": "2026-01-01", "end": "2026-06-01"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["run_id"] == "r1"
