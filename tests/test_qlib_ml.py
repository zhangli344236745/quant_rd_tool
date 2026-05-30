"""Qlib ML module tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_rd_tool.qlib_ml import MIN_TRAINING_BARS, run_lgb_analysis, run_ml_analysis


def test_run_xgb_skips_short_series(tmp_path):
    result = run_ml_analysis(
        str(tmp_path),
        "SH600519",
        start_date="2024-01-01",
        end_date="2024-12-31",
        num_bars=100,
    )
    assert result["skipped"] is True
    assert result["enabled"] is False


@pytest.mark.skipif(
    not Path("data/stocks/SH600519/qlib").exists(),
    reason="requires local SH600519 qlib data",
)
def test_run_xgb_on_local_data():
    root = Path("data/stocks/SH600519")
    import pandas as pd

    df = pd.read_csv(root / "ohlcv.csv", parse_dates=["date"])
    assert len(df) >= MIN_TRAINING_BARS
    result = run_ml_analysis(
        str((root / "qlib").resolve()),
        "SH600519",
        start_date="2020-01-01",
        end_date=str(df["date"].max().date()),
        num_bars=len(df),
        algorithm="xgb",
    )
    assert result["enabled"] is True


@pytest.mark.skipif(
    not Path("data/stocks/SH600519/qlib").exists(),
    reason="requires local SH600519 qlib data",
)
def test_run_lgb_on_local_data():
    root = Path("data/stocks/SH600519")
    import pandas as pd

    df = pd.read_csv(root / "ohlcv.csv", parse_dates=["date"])
    result = run_lgb_analysis(
        str((root / "qlib").resolve()),
        "SH600519",
        start_date="2020-01-01",
        end_date=str(df["date"].max().date()),
        num_bars=len(df),
    )
    assert result["enabled"] is True
    assert "test_metrics" in result
    assert result["top_features"]
