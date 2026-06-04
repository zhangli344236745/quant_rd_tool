from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quant_rd_tool.crypto_zipline_pandas import run_bar_backtest
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
