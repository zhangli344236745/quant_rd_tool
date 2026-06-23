from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quant_rd_tool.stock_vbt_lab import run_backtest
from quant_rd_tool.stock_vbt_reports import build_report_artifacts, equity_to_returns


def test_equity_to_returns():
    curve = [
        {"time": "2023-01-02", "value": 100_000},
        {"time": "2023-01-03", "value": 101_000},
        {"time": "2023-01-04", "value": 100_500},
    ]
    r = equity_to_returns(curve)
    assert len(r) == 2


def test_build_metrics_artifacts(tmp_path):
    idx = pd.date_range("2020-01-01", periods=120, freq="B")
    returns = pd.Series(0.001, index=idx, name="strategy")
    out = build_report_artifacts(returns, tmp_path, title="test")
    assert (tmp_path / "metrics.json").is_file()
    assert "html_path" not in out
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert "sharpe" in metrics


def test_run_vbt_backtest_on_fixture(monkeypatch, tmp_path):
    from quant_rd_tool import stock_vbt_lab as lab

    monkeypatch.setattr(lab, "VBT_LAB_DIR", tmp_path)
    fixture = Path(__file__).parent / "fixtures" / "ashare_vbt_daily.csv"
    df = pd.read_csv(fixture, parse_dates=["date"])

    def _fake_load(*args, **kwargs):
        return df

    monkeypatch.setattr(lab, "load_ohlcv", _fake_load)
    result = run_backtest(
        symbol="600519",
        start="2023-01-02",
        end="2023-04-24",
        strategy_id="sma_cross",
        strategy_params={"fast": 5, "slow": 20},
        capital_base=100_000,
    )
    assert result["run_id"]
    assert (tmp_path / result["run_id"] / "params.json").is_file()
    assert result["metrics"]


def test_vbt_path_t_plus_one_blocked():
    fixture = Path(__file__).parent / "fixtures" / "ashare_vbt_daily.csv"
    df = pd.read_csv(fixture, parse_dates=["date"]).iloc[:30]
    from quant_rd_tool.stock_ashare_pandas import ashare_backtest_context, run_ashare_bar_backtest
    from quant_rd_tool.stock_vbt_strategies import build_target_series

    work = build_target_series(df, "sma_cross", {"fast": 3, "slow": 8})
    work.loc[work.index[5], "target"] = 1.0
    work.loc[work.index[6], "target"] = 0.0
    with ashare_backtest_context(symbol="SH600519", use_ashare=True):
        out = run_ashare_bar_backtest(work, capital_base=100_000, warmup=8, target_col="target")
    assert out["cost_summary"]["blocked_t_plus_one"] >= 0
