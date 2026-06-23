from __future__ import annotations

from fastapi.testclient import TestClient

from quant_rd_tool.main import app

client = TestClient(app)


def test_vbt_strategies_route():
    r = client.get("/api/v1/stocks/vbt/strategies")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 4
    assert {s["id"] for s in body} == {"sma_cross", "rsi_revert", "macd_cross", "bb_breakout"}


def test_vbt_backtest_route(monkeypatch):
    from quant_rd_tool import stock_vbt_lab as lab

    monkeypatch.setattr(
        lab,
        "run_backtest",
        lambda **kw: {
            "run_id": "11111111-1111-1111-1111-111111111111",
            "symbol": "SH600519",
            "strategy_id": kw["strategy_id"],
            "strategy_name": "双均线交叉",
            "metrics": {"sharpe": 1.2, "total_return": 0.1},
            "execution_stats": {},
            "trades_count": 2,
            "equity_curve": [],
            "trades": [],
        },
    )
    r = client.post(
        "/api/v1/stocks/vbt/backtest",
        json={
            "symbol": "600519",
            "start": "2023-01-01",
            "end": "2023-06-01",
            "strategy_id": "sma_cross",
            "strategy_params": {"fast": 10, "slow": 30},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "11111111-1111-1111-1111-111111111111"
    assert "metrics" in body


def test_vbt_runs_route(monkeypatch):
    from quant_rd_tool import stock_vbt_lab as lab

    monkeypatch.setattr(lab, "list_runs", lambda **kw: [{"run_id": "r1", "symbol": "SH600519"}])
    r = client.get("/api/v1/stocks/vbt/runs")
    assert r.status_code == 200
    assert r.json()["items"][0]["run_id"] == "r1"


def test_vbt_tune_route(monkeypatch):
    from quant_rd_tool import stock_vbt_optuna as opt

    monkeypatch.setattr(
        opt,
        "run_optuna_tune",
        lambda **kw: {
            "run_id": "t1",
            "symbol": "SH600519",
            "strategy_id": "sma_cross",
            "strategy_name": "双均线",
            "best_params": {"fast": 5, "slow": 20},
            "best_sharpe": 1.1,
            "train_metrics": {"sharpe": 1.1},
            "test_metrics": {"sharpe": 0.8},
            "n_trials": 10,
            "train_ratio": 0.7,
        },
    )
    r = client.post(
        "/api/v1/stocks/vbt/tune",
        json={
            "symbol": "600519",
            "start": "2023-01-01",
            "end": "2023-06-01",
            "strategy_id": "sma_cross",
            "n_trials": 10,
        },
    )
    assert r.status_code == 200
    assert r.json()["best_params"]["fast"] == 5


def test_vbt_ml_score_route(monkeypatch):
    from quant_rd_tool import stock_vbt_ml as ml

    monkeypatch.setattr(
        ml,
        "screen_universe",
        lambda **kw: {
            "run_id": "m1",
            "items": [{"symbol": "SH600519", "score": 0.02}],
            "errors": [],
            "universe_size": 1,
            "scored": 1,
            "algorithm": "lgb",
        },
    )
    r = client.post(
        "/api/v1/stocks/vbt/ml/score",
        json={"symbols": ["600519"], "start": "2023-01-01", "end": "2023-06-01"},
    )
    assert r.status_code == 200
    assert r.json()["items"][0]["symbol"] == "SH600519"


def test_vbt_scheduler_status_route():
    r = client.get("/api/v1/stocks/vbt/scheduler/status")
    assert r.status_code == 200
    assert "running" in r.json()


def test_vbt_tune_runs_route(monkeypatch):
    from quant_rd_tool import stock_vbt_optuna as opt

    monkeypatch.setattr(
        opt,
        "list_tune_runs",
        lambda **kw: [{"run_id": "t1", "best_sharpe": 1.0}],
    )
    r = client.get("/api/v1/stocks/vbt/tune/runs")
    assert r.status_code == 200
    assert r.json()["items"][0]["run_id"] == "t1"


def test_vbt_backtest_job_route():
    from quant_rd_tool.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/jobs/vbt-backtest",
            json={
                "symbol": "600519",
                "start": "2023-01-01",
                "end": "2023-06-01",
                "strategy_id": "sma_cross",
            },
        )
    assert r.status_code == 202
    assert "job_id" in r.json()
