from quant_rd_tool.binance_perp_bot import _decide_plan


def test_same_side_noop():
    plan = _decide_plan(position_side="long", target_side="long", hold_behavior="do_nothing")
    assert plan == {"close": False, "open": False}


def test_flip_closes_then_opens():
    plan = _decide_plan(position_side="long", target_side="short", hold_behavior="do_nothing")
    assert plan["close"] is True
    assert plan["open"] is True

