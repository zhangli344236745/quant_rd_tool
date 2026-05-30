"""Tests for crypto scheduler and incremental storage (no network)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analysis import format_period_bounds
from quant_rd_tool.crypto_storage import merge_ohlcv, sync_ohlcv


def _bars(n: int, start: str = "2024-01-01 00:00:00", freq: str = "5min") -> pd.DataFrame:
    dates = pd.date_range(start, periods=n, freq=freq)
    close = 100 + pd.Series(range(n))
    ts = (dates.astype("int64") // 10**6).astype(int)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "date": dates,
            "symbol": ["CRYPTO_BTC"] * n,
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1e6,
        }
    )


def test_merge_ohlcv_dedupes():
    a = _bars(5)
    b = _bars(3, start="2024-01-01 00:25:00")
    merged = merge_ohlcv(a, b)
    assert len(merged) == 8
    assert merged["date"].is_monotonic_increasing


def test_format_period_bounds_intraday():
    df = _bars(10)
    start, end = format_period_bounds(df, "5m")
    assert ":" in start
    assert ":" in end


def test_sync_ohlcv_backfill_and_incremental(tmp_path: Path):
    initial = _bars(100)
    extra = _bars(5, start="2024-01-01 08:20:00")

    with patch("quant_rd_tool.crypto_storage.cxt.fetch_ohlcv_history", return_value=initial):
        df1, meta1 = sync_ohlcv("BTC", data_dir=tmp_path, timeframe="5m", backfill_days=7)
    assert meta1["last_sync_action"] == "backfill"
    assert len(df1) == 100

    with patch("quant_rd_tool.crypto_storage.cxt.fetch_ohlcv_incremental", return_value=extra):
        df2, meta2 = sync_ohlcv("BTC", data_dir=tmp_path, timeframe="5m", backfill_days=7)
    assert meta2["last_sync_action"] == "incremental"
    assert len(df2) == 105
    assert meta2["new_bars"] == 5


def test_run_scheduled_cycle_mock(tmp_path: Path):
    from quant_rd_tool.crypto_scheduler import run_scheduled_cycle

    df = _bars(3000)
    with patch("quant_rd_tool.crypto_scheduler.sync_ohlcv", return_value=(df, {"new_bars": 6})):
        with patch(
            "quant_rd_tool.crypto_scheduler.analyze_crypto_from_df",
            return_value={
                "symbol": "CRYPTO_BTC",
                "pair": "BTC/USDT",
                "combined_signal": {"stance": "看涨", "action": "buy"},
                "period": {"start": "2024-01-01", "end": "2024-01-11"},
                "narrative": {"advice": "test"},
            },
        ):
            results = run_scheduled_cycle(
                ["BTC"],
                data_dir=tmp_path,
                timeframe="5m",
                with_ml=False,
                save_snapshot=False,
            )
    assert len(results) == 1
    assert results[0]["combined_signal"]["stance"] == "看涨"


def test_timeframe_helpers():
    assert cxt.timeframe_to_ms("5m") == 300_000
    assert cxt.timeframe_to_qlib_freq("5m") == "5min"
    assert cxt.timeframe_to_qlib_freq("1d") == "day"
