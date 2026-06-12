from __future__ import annotations

import numpy as np
import pandas as pd

from quant_rd_tool.crypto_signal import (
    build_enhanced_signal,
    compute_atr_pct,
    higher_timeframe_for,
    volume_confirms,
)


def _trend_df(n: int, *, slope: float, vol_last: float | None = None) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    base = 100 + slope * np.arange(n)
    close = base + np.sin(np.arange(n) / 5)
    high = close + 1.0
    low = close - 1.0
    volume = np.full(n, 1000.0)
    if vol_last is not None:
        volume[-1] = vol_last
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "CRYPTO_BTC",
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def test_higher_timeframe_for():
    assert higher_timeframe_for("5m") == "1h"
    assert higher_timeframe_for("1h") == "1d"
    assert higher_timeframe_for("unknown") == "1d"


def test_compute_atr_pct_positive():
    df = _trend_df(60, slope=0.5)
    atr_pct = compute_atr_pct(df, period=14)
    assert atr_pct is not None and atr_pct > 0


def test_volume_confirms_detects_spike():
    df = _trend_df(40, slope=0.5, vol_last=5000.0)
    assert volume_confirms(df, lookback=20, min_ratio=1.5) is True
    flat = _trend_df(40, slope=0.5)
    assert volume_confirms(flat, lookback=20, min_ratio=1.5) is False


def test_htf_confirmation_gates_conflicting_signal():
    up = _trend_df(120, slope=0.8)  # base bullish
    htf_down = _trend_df(120, slope=-0.8)  # higher timeframe bearish
    out = build_enhanced_signal(up, htf_down, timeframe="1h", require_htf_confirm=True)
    # base would buy, but htf conflicts → gated to hold
    if out["base_action"] == "buy":
        assert out["action"] == "hold"
        assert out["gated"] is True
        assert any("高周期" in g for g in out["gates"])


def test_htf_confirmation_passes_aligned_signal():
    up = _trend_df(120, slope=0.8)
    htf_up = _trend_df(120, slope=0.8)
    out = build_enhanced_signal(up, htf_up, timeframe="1h", require_htf_confirm=True)
    if out["base_action"] == "buy":
        assert out["action"] == "buy"
        assert out["gated"] is False


def test_volatility_floor_gates_low_vol():
    up = _trend_df(120, slope=0.8)
    out = build_enhanced_signal(
        up, None, timeframe="1d", require_htf_confirm=False, min_atr_pct=0.5
    )
    if out["base_action"] in ("buy", "sell"):
        assert out["action"] == "hold"
        assert any("波动率过低" in g for g in out["gates"])
