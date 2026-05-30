import pandas as pd

from quant_rd_tool.perp_risk import compute_atr, compute_sl_tp_prices_atr


def test_atr_basic():
    df = pd.DataFrame(
        {
            "high": [10, 11, 12],
            "low": [9, 10, 11],
            "close": [9.5, 10.5, 11.5],
        }
    )
    atr = compute_atr(df, period=2)
    assert atr > 0


def test_sl_tp_long_atr():
    sl, tp = compute_sl_tp_prices_atr(side="long", ref_price=100.0, atr=2.0, sl_atr=1.5, tp_atr=2.5)
    assert sl == 97.0
    assert tp == 105.0


def test_sl_tp_short_atr():
    sl, tp = compute_sl_tp_prices_atr(side="short", ref_price=100.0, atr=2.0, sl_atr=1.5, tp_atr=2.5)
    assert sl == 103.0
    assert tp == 95.0

