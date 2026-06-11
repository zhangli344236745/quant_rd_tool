from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quant_rd_tool.crypto_zipline_pandas import backtest_cost_context, run_bar_backtest
from quant_rd_tool.crypto_zipline_storage import list_runs, load_run, save_run
from quant_rd_tool.crypto_zipline_strategies import list_strategies, run_ma_crossover


def _sample_df(n: int = 80) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        price += (1 if i % 7 < 4 else -1) * 0.5
        rows.append(
            {
                "date": f"2026-01-{(i % 28) + 1:02d} 12:00:00",
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 1000 + i,
            }
        )
    return pd.DataFrame(rows)


def test_run_bar_backtest_metrics():
    df = _sample_df()
    df["target"] = (df["close"].rolling(5).mean() > df["close"].rolling(10).mean()).astype(float)
    out = run_bar_backtest(df, capital_base=10_000, warmup=12)
    assert "metrics" in out
    assert "equity_curve" in out
    assert len(out["equity_curve"]) == len(df)
    assert out["final_signal"]["position"] in ("long", "flat", "short")


def test_run_bar_backtest_costs_reduce_return():
    df = _sample_df(100)
    df["target"] = (df["close"].rolling(5).mean() > df["close"].rolling(10).mean()).astype(float)
    free = run_bar_backtest(df, capital_base=10_000, warmup=12, commission_pct=0.0, slippage_pct=0.0)
    costly = run_bar_backtest(df, capital_base=10_000, warmup=12, commission_pct=0.002, slippage_pct=0.001)
    assert costly["metrics"]["total_return"] < free["metrics"]["total_return"]
    assert costly["metrics"]["total_fees"] > 0
    assert free["metrics"]["total_fees"] == 0
    assert costly["cost_model"]["commission_pct"] == 0.002
    assert all("fee" in t for t in costly["trades"])


def test_run_bar_backtest_extended_metrics():
    df = _sample_df(100)
    df["target"] = (df["close"].rolling(5).mean() > df["close"].rolling(10).mean()).astype(float)
    out = run_bar_backtest(
        df, capital_base=10_000, warmup=12, commission_pct=0.0, slippage_pct=0.0, bars_per_year=35040
    )
    m = out["metrics"]
    assert "sortino" in m
    assert "annualized_return" in m
    assert "buy_hold_return" in m
    assert "excess_vs_hold" in m
    assert abs(m["excess_vs_hold"] - (m["total_return"] - m["buy_hold_return"])) < 1e-6
    if m["trade_count"] >= 2:
        assert "win_rate" in m


def test_backtest_cost_context_injects_defaults():
    df = _sample_df(100)
    df["target"] = (df["close"].rolling(5).mean() > df["close"].rolling(10).mean()).astype(float)
    with backtest_cost_context(commission_pct=0.005, slippage_pct=0.0, bars_per_year=365):
        out = run_bar_backtest(df, capital_base=10_000, warmup=12)
    assert out["cost_model"]["commission_pct"] == 0.005
    assert "annualized_return" in out["metrics"]


def test_sharpe_annualization_stable_with_length():
    """Sharpe should not blow up just because the sample is longer."""
    import numpy as np

    rng = np.random.default_rng(42)

    def _df(n: int) -> pd.DataFrame:
        steps = rng.normal(0.0005, 0.01, n)
        price = 100 * (1 + pd.Series(steps)).cumprod()
        return pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=n, freq="15min").astype(str),
                "open": price,
                "high": price * 1.001,
                "low": price * 0.999,
                "close": price,
                "volume": 1000.0,
                "target": 1.0,
            }
        )

    short = run_bar_backtest(
        _df(200), capital_base=10_000, warmup=5, commission_pct=0, slippage_pct=0, bars_per_year=35040
    )
    long = run_bar_backtest(
        _df(2000), capital_base=10_000, warmup=5, commission_pct=0, slippage_pct=0, bars_per_year=35040
    )
    # Same annualization factor: longer sample shouldn't yield mechanically larger sharpe
    assert abs(long["metrics"]["sharpe"]) < abs(short["metrics"]["sharpe"]) * 10 + 5


def test_ma_crossover_strategy():
    df = _sample_df(100)
    out = run_ma_crossover(df, {"fast": 5, "slow": 15}, 50_000)
    assert out["metrics"]["trade_count"] >= 0


def test_list_strategies():
    strategies = list_strategies()
    ids = {s["id"] for s in strategies}
    assert "ma_crossover" in ids
    assert "momentum_rsi" in ids
    assert len(strategies) >= 19


def test_save_and_load_run(tmp_path: Path):
    result = {
        "run_id": "test-run-1",
        "symbol": "BTC",
        "strategy": "ma_crossover",
        "timeframe": "15m",
        "engine": "pandas",
        "metrics": {"total_return": 0.1, "sharpe": 1.0, "max_drawdown": -0.05, "trade_count": 3},
        "trades": [{"side": "buy", "price": 100}],
        "equity_curve": [{"time": "t", "value": 10000}],
    }
    save_run(tmp_path, result)
    loaded = load_run(tmp_path, "test-run-1")
    assert loaded is not None
    assert loaded["symbol"] == "BTC"
    assert len(loaded.get("trades", [])) == 1
    runs = list_runs(tmp_path, limit=5)
    assert runs[0]["run_id"] == "test-run-1"
