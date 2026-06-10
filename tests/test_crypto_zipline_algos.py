from __future__ import annotations

import pandas as pd

from quant_rd_tool.crypto_zipline_bundle import df_fingerprint
from quant_rd_tool.crypto_zipline_strategies import list_strategies
from quant_rd_tool.crypto_zipline_strategies.signals import (
    adx_trend_target,
    bollinger_target,
    donchian_breakout_target,
    ema_crossover_target,
    golden_cross_target,
    ichimoku_cloud_target,
    keltner_breakout_target,
    ma_crossover_target,
    macd_cross_target,
    psar_trend_target,
    rsi_target,
    supertrend_sized_target,
    supertrend_target,
    vwap_trend_target,
)


def test_ma_crossover_target():
    closes = [100.0 + i for i in range(40)]
    assert ma_crossover_target(closes, fast=5, slow=10) == 1.0
    closes_down = [100.0 - i * 0.5 for i in range(40)]
    assert ma_crossover_target(closes_down, fast=5, slow=10) == 0.0
    assert ma_crossover_target([1.0, 2.0], fast=5, slow=10) is None


def test_rsi_target_holds_position():
    oversold_closes = [100.0 - i * 2 for i in range(20)]
    assert rsi_target(oversold_closes, period=14, oversold=30, overbought=70) == 1.0
    mid = oversold_closes + [oversold_closes[-1] + 0.5] * 5
    assert rsi_target(mid, period=14, oversold=30, overbought=70, last_target=1.0) == 1.0


def test_new_strategy_signals():
    up = [100.0 + i for i in range(50)]
    assert ema_crossover_target(up, fast=5, slow=15) == 1.0
    assert bollinger_target(up, period=20, std_mult=2.0, last_target=0.0) in (0.0, 1.0)
    assert donchian_breakout_target(up, channel=10) == 1.0
    assert macd_cross_target(up, fast=5, slow=15, signal=5) in (0.0, 1.0)


def test_tv_style_strategies():
    up = [100.0 + i * 0.3 for i in range(80)]
    highs = [p + 0.5 for p in up]
    lows = [p - 0.5 for p in up]
    assert supertrend_target(up, highs, lows, atr_len=10, factor=3.0) in (0.0, 1.0)
    sized = supertrend_sized_target(
        up, highs, lows, atr_len=10, factor=3.0, max_position=0.5, min_position=0.15
    )
    assert sized is not None and 0.0 <= sized <= 0.5
    assert golden_cross_target(up, fast=5, slow=20) == 1.0
    assert adx_trend_target(highs, lows, up, period=14, adx_threshold=10) in (0.0, 1.0)
    assert psar_trend_target(highs, lows, up) in (0.0, 1.0)
    assert keltner_breakout_target(up, highs, lows, period=10, atr_mult=1.5) in (0.0, 1.0, None)
    assert ichimoku_cloud_target(highs, lows, up, tenkan=9, kijun=20) in (0.0, 1.0, None)
    vols = [1000.0 + i for i in range(len(up))]
    assert vwap_trend_target(up, highs, lows, vols, lookback=20) in (0.0, 1.0)


def test_list_strategies_includes_new():
    ids = {s["id"] for s in list_strategies()}
    for sid in (
        "ema_trend",
        "bollinger_revert",
        "donchian_breakout",
        "macd_cross",
        "volume_breakout",
        "supertrend",
        "supertrend_sized",
        "stoch_rsi",
        "golden_cross",
        "ema_rsi_filter",
        "macd_rsi_confirm",
        "adx_trend",
        "psar_trend",
        "keltner_breakout",
        "bb_squeeze",
        "ichimoku_cloud",
        "vwap_trend",
        "wavetrend",
        "xgb_alpha158",
    ):
        assert sid in ids
    assert len(ids) >= 53


def test_df_fingerprint_stable():
    df = pd.DataFrame(
        {
            "timestamp": [1000, 2000],
            "close": [1.0, 2.0],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "volume": [10.0, 20.0],
        }
    )
    start = pd.Timestamp("2026-01-01")
    end = pd.Timestamp("2026-01-02")
    a = df_fingerprint("BTC", df, timeframe="15m", ingest_start=start, ingest_end=end)
    b = df_fingerprint("BTC", df, timeframe="15m", ingest_start=start, ingest_end=end)
    assert a == b
