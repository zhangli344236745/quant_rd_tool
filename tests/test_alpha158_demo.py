"""Alpha158 demo: verify feature matrix can be built from local qlib_5m data."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QLIB_5M = PROJECT_ROOT / "data" / "crypto" / "CRYPTO_BTC" / "qlib_5m"
CSV_5M = PROJECT_ROOT / "data" / "crypto" / "CRYPTO_BTC" / "ohlcv_5m.csv"


def _has_min_span_days(csv_path: Path, *, min_span_days: int) -> bool:
    try:
        import pandas as pd

        df = pd.read_csv(csv_path, usecols=["date"])
        df["date"] = pd.to_datetime(df["date"])
        if df.empty:
            return False
        span_days = (df["date"].max() - df["date"].min()).days
        return span_days >= min_span_days
    except Exception:
        return False


@pytest.mark.skipif(
    not QLIB_5M.joinpath("calendars", "5min.txt").exists()
    or not CSV_5M.exists()
    or not _has_min_span_days(CSV_5M, min_span_days=60),
    reason="需要至少约 60 天 BTC 5m qlib 数据: quant-rd crypto analyze --symbol BTC --timeframe 5m --backfill-days 120",
)
def test_alpha158_produces_features():
    import sys

    src = str(PROJECT_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    from tools.demo_alpha158 import run_alpha158_demo

    summary = run_alpha158_demo("BTC")

    assert summary["train_rows"] > 1000
    assert summary["feature_count"] >= 100
    assert summary["label_non_null"] > 1000
