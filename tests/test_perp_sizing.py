from quant_rd_tool.binance_perp_bot import _calc_amount_from_notional


def test_calc_amount_basic():
    amt = _calc_amount_from_notional(notional_usdt=300, price=30000, amount_step=0.001)
    assert amt == 0.01


def test_calc_amount_rounds_down_to_step():
    amt = _calc_amount_from_notional(notional_usdt=305, price=30000, amount_step=0.001)
    assert amt == 0.01

