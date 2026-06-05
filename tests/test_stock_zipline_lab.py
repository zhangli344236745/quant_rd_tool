from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_rd_tool import akshare_data as ak_data
from quant_rd_tool.stock_storage import csv_path, save_csv, stock_root
from quant_rd_tool.stock_zipline_bundle import data_status, load_ohlcv_window
from quant_rd_tool.stock_zipline_lab import lab_status
from quant_rd_tool.stock_zipline_runner import run_pandas_backtest
from quant_rd_tool.stock_zipline_timeframes import normalize_timeframe


def _daily_df(n: int = 120) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        price += (1 if i % 11 < 6 else -1) * 0.3
        rows.append(
            {
                "date": f"2024-{(i % 12) + 1:02d}-{(i % 20) + 1:02d}",
                "symbol": "SH600519",
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 1_000_000 + i,
            }
        )
    return pd.DataFrame(rows)


def test_normalize_timeframe_daily():
    assert normalize_timeframe("daily") == "1d"
    assert normalize_timeframe("1d") == "1d"


def test_load_ohlcv_window(tmp_path: Path):
    code = "600519"
    root = stock_root(tmp_path, code)
    save_csv(_daily_df(80), csv_path(root))
    df = load_ohlcv_window(code, data_dir=tmp_path, lookback_days=365, range_start="2024-01-01", range_end="2025-12-31")
    assert len(df) >= 50
    st = data_status(code, data_dir=tmp_path)
    assert st["ready"] is True
    assert st["symbol"] == ak_data.to_qlib_code(code)


def test_pandas_backtest_on_daily(tmp_path: Path):
    df = _daily_df(100)
    out = run_pandas_backtest(df, strategy_id="ma_crossover", strategy_params={"fast": 5, "slow": 20}, capital_base=50_000)
    assert out["engine"] == "pandas"
    assert out["market"] == "stock"
    assert "metrics" in out


def test_lab_status(tmp_path: Path):
    code = "600519"
    root = stock_root(tmp_path, code)
    save_csv(_daily_df(30), csv_path(root))
    st = lab_status(str(tmp_path), symbols=[code])
    assert st["market"] == "stock"
    assert st["default_timeframe"] == "1d"
