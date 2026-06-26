from __future__ import annotations

import pandas as pd
import pytest

from quant_rd_tool.crypto_volume_advisor import (
    build_volume_advice,
    classify_volume_scheme,
    compute_volume_metrics,
)


def _sample_df(*, vol_scale: float = 1.0, price_trend: float = 0.002) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    rows = []
    price = 100.0
    for i, dt in enumerate(dates):
        price *= 1.0 + price_trend
        rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "symbol": "BTC",
                "open": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 1000.0 * vol_scale * (1.5 if i >= 35 else 1.0),
            }
        )
    return pd.DataFrame(rows)


def test_compute_volume_metrics_breakout():
    df = _sample_df(vol_scale=1.0, price_trend=0.004)
    metrics = compute_volume_metrics(df, timeframe="1d")
    assert metrics["volume_ratio_5d_vs_20d"] is not None
    assert metrics["volume_ratio_5d_vs_20d"] > 1.1
    assert metrics["price_volume_alignment"] in {"bullish_confirm", "accumulation", "neutral"}


def test_classify_breakout_confirmed():
    metrics = {
        "volume_ratio_5d_vs_20d": 1.4,
        "turnover_percentile_60": 75,
        "return_5bar": 0.05,
        "price_volume_alignment": "bullish_confirm",
    }
    assert classify_volume_scheme(metrics) == "breakout_confirmed"


def test_classify_low_liquidity():
    metrics = {
        "volume_ratio_5d_vs_20d": 0.4,
        "turnover_percentile_60": 10,
        "return_5bar": 0.0,
        "price_volume_alignment": "neutral",
    }
    assert classify_volume_scheme(metrics) == "low_liquidity_warn"


def test_build_advice_strong_buy_with_technical():
    metrics = {
        "volume_ratio_5d_vs_20d": 1.35,
        "turnover_ratio_5d_vs_20d": 1.2,
        "turnover_percentile_60": 80,
        "return_5bar": 0.04,
    }
    advice = build_volume_advice(
        metrics,
        scheme="breakout_confirmed",
        technical_stance="看涨",
    )
    assert advice["level"] == "strong_buy"
    assert advice["stance"] == "看涨"
    assert advice["suggested_max_position_pct"] > 0.3


def test_advise_spot_volume_rejects_non_focus_symbol():
    from quant_rd_tool.crypto_volume_advisor import advise_spot_volume

    with pytest.raises(ValueError, match="supports"):
        advise_spot_volume("SOL")
