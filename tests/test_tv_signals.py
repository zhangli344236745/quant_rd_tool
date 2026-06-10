"""Tests for extended TV signals."""

import pytest

from quant_rd_tool.crypto_zipline_strategies.signals import signal_for_strategy
from quant_rd_tool.crypto_zipline_strategies.tv_catalog import NEW_TV_IDS, list_tv_strategies

NEW_IDS = sorted(NEW_TV_IDS)


def test_wavetrend_warmup():
    closes = [100.0] * 20
    r = signal_for_strategy(
        "wavetrend",
        closes,
        [0.0] * 20,
        {"channel_len": 10, "avg_len": 21},
        highs=closes,
        lows=closes,
    )
    assert r is None


def test_hull_ma_uptrend():
    closes = [float(100 + i) for i in range(80)]
    r = signal_for_strategy(
        "hull_ma_trend",
        closes,
        [1.0] * 80,
        {"period": 55},
        highs=closes,
        lows=closes,
    )
    assert r == 1.0


@pytest.mark.parametrize("sid", NEW_IDS)
def test_new_signal_eventually_returns_target(sid):
    spec = next(s for s in list_tv_strategies() if s["id"] == sid)
    params = dict(spec["default_params"])
    n = max(spec["min_bars"] + 50, 300)
    closes = [100 + (i % 11) - 5 + i * 0.01 for i in range(n)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    volumes = [1000.0 + i for i in range(n)]
    opens = [closes[max(0, i - 1)] for i in range(n)]
    last = 0.0
    got = None
    for i in range(n):
        t = signal_for_strategy(
            sid,
            closes[: i + 1],
            volumes[: i + 1],
            params,
            highs=highs[: i + 1],
            lows=lows[: i + 1],
            opens=opens[: i + 1],
            last_target=last,
        )
        if t is not None:
            got = t
            last = t
    assert got is not None
    assert got in (0.0, 1.0) or 0.0 <= got <= 1.0
