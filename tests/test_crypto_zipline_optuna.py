from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from quant_rd_tool.crypto_zipline_optuna import (
    CryptoZiplineTuneManager,
    _metric_value,
    run_optuna_tune_sync,
)


def _fake_df() -> pd.DataFrame:
    rows = []
    for i in range(1, 121):
        day = i
        month = 1 + (day - 1) // 28
        dom = ((day - 1) % 28) + 1
        rows.append(
            {
                "date": f"2026-{month:02d}-{dom:02d}",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + (i % 5),
                "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows)


def _fake_zipline_result(sharpe: float = 0.5, total_return: float = 0.1) -> dict:
    return {
        "engine": "zipline",
        "metrics": {
            "sharpe": sharpe,
            "total_return": total_return,
            "max_drawdown": -0.05,
            "trade_count": 3,
        },
        "trades": [],
        "equity_curve": [],
    }


def test_metric_value_sharpe_and_calmar():
    assert _metric_value({"sharpe": 0.42}, "sharpe") == pytest.approx(0.42)
    assert _metric_value({"total_return": 0.2, "max_drawdown": -0.1}, "calmar") == pytest.approx(2.0)
    assert _metric_value({}, "sharpe") == -999.0


@patch("quant_rd_tool.crypto_zipline_optuna.run_zipline_backtest")
@patch("quant_rd_tool.crypto_zipline_optuna.load_ohlcv_window")
def test_run_optuna_tune_sync_progress_on_first_trial(mock_load, mock_run):
    mock_load.return_value = _fake_df()
    mock_run.return_value = _fake_zipline_result(sharpe=0.42)
    progress: list[dict] = []

    run_optuna_tune_sync(
        symbol="BTC",
        start="2026-01-01",
        end="2026-02-10",
        strategy_id="donchian_breakout",
        n_trials=3,
        train_ratio=0.7,
        data_dir="data/crypto",
        timeframe="15m",
        progress_cb=progress.append,
    )
    assert progress
    assert progress[0]["current_trial"] == 1
    assert progress[0]["best_value"] == pytest.approx(0.42)


@patch("quant_rd_tool.crypto_zipline_optuna.run_zipline_backtest")
@patch("quant_rd_tool.crypto_zipline_optuna.load_ohlcv_window")
def test_run_optuna_tune_sync_mock(mock_load, mock_run):
    mock_load.return_value = _fake_df()
    scores = [0.1, 0.2, 0.35, 0.35, 0.28]
    call_idx = {"n": 0}

    def _run(**kwargs):
        idx = min(call_idx["n"], len(scores) - 1)
        call_idx["n"] += 1
        return _fake_zipline_result(sharpe=scores[idx])

    mock_run.side_effect = _run
    out = run_optuna_tune_sync(
        symbol="BTC",
        start="2026-01-01",
        end="2026-02-10",
        strategy_id="donchian_breakout",
        n_trials=3,
        train_ratio=0.7,
        data_dir="data/crypto",
        timeframe="15m",
    )
    assert out["strategy_id"] == "donchian_breakout"
    assert "best_params" in out
    assert out["best_value"] >= 0.2
    assert out["train_metrics"]["sharpe"] is not None
    assert mock_run.call_count >= 5


@patch("quant_rd_tool.crypto_zipline_optuna.run_optuna_tune_sync")
def test_tune_manager_submit_and_complete(mock_sync):
    mock_sync.return_value = {
        "run_id": "r1",
        "symbol": "BTC",
        "strategy_id": "ma_crossover",
        "strategy_name": "均线交叉",
        "timeframe": "15m",
        "objective": "sharpe",
        "best_params": {"fast": 8, "slow": 21},
        "best_value": 0.5,
        "train_metrics": {"sharpe": 0.5},
        "test_metrics": {"sharpe": 0.3},
        "n_trials": 3,
        "train_ratio": 0.7,
    }
    mgr = CryptoZiplineTuneManager()
    started = mgr.submit(
        symbol="BTC",
        start="2026-01-01",
        end="2026-02-01",
        strategy_id="ma_crossover",
        n_trials=3,
    )
    job_id = started["job_id"]
    import time

    for _ in range(50):
        job = mgr.get_job(job_id)
        if job and job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    job = mgr.get_job(job_id)
    assert job is not None
    assert job["status"] == "completed"
    assert job["result"]["best_params"]["fast"] == 8
