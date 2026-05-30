"""Tests for qlib provider re-initialization."""

from __future__ import annotations

from pathlib import Path

from quant_rd_tool.qlib_init import init_qlib, reset_qlib_init_state


def test_init_qlib_switches_provider():
    reset_qlib_init_state()
    root = Path("data/crypto")
    btc_day = root / "CRYPTO_BTC" / "qlib"
    eth_5m = root / "CRYPTO_ETH" / "qlib_5m"
    if not btc_day.exists() or not eth_5m.exists():
        return

    from quant_rd_tool.qlib_ml import _build_handler, _time_segments, _validate_dataset_segments
    from qlib.data.dataset import DatasetH
    import pandas as pd

    init_qlib(str(btc_day.resolve()))
    init_qlib(str(eth_5m.resolve()))

    df = pd.read_csv(root / "CRYPTO_ETH" / "ohlcv_5m.csv")
    df["date"] = pd.to_datetime(df["date"])
    start = df["date"].min().strftime("%Y-%m-%d %H:%M:%S")
    end = df["date"].max().strftime("%Y-%m-%d %H:%M:%S")
    seg = _time_segments(start, end, min_span_days=60, intraday=True)
    h = _build_handler("CRYPTO_ETH", start, end, fit_end=seg["train"][1], qlib_freq="5min")
    ds = DatasetH(h, segments=seg)
    counts = _validate_dataset_segments(ds)
    assert counts["train"] >= 100
    reset_qlib_init_state()
