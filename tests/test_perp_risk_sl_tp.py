from quant_rd_tool.perp_risk import compute_sl_tp_prices


def test_sl_tp_long_pct():
    sl, tp = compute_sl_tp_prices(side="long", ref_price=100.0, sl_pct=0.01, tp_pct=0.02)
    assert sl == 99.0
    assert tp == 102.0


def test_sl_tp_short_pct():
    sl, tp = compute_sl_tp_prices(side="short", ref_price=100.0, sl_pct=0.01, tp_pct=0.02)
    assert sl == 101.0
    assert tp == 98.0

