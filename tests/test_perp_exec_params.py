from quant_rd_tool.perp_exec import (
    NativeProtectionParams,
    build_binance_native_protection_orders,
    trigger_source_to_working_type,
)


def test_trigger_source_mapping():
    assert trigger_source_to_working_type("last") == "CONTRACT_PRICE"
    assert trigger_source_to_working_type("mark") == "MARK_PRICE"


def test_native_protection_intents_include_required_params():
    p = NativeProtectionParams(
        symbol="BTC/USDT:USDT",
        amount=0.01,
        sl_stop_price=99000.0,
        tp_stop_price=101000.0,
        working_type="CONTRACT_PRICE",
        sl_client_order_id="abc_1",
        tp_client_order_id="abc_2",
    )
    sl, tp = build_binance_native_protection_orders(p)
    assert sl["type"] == "STOP_MARKET"
    assert tp["type"] == "TAKE_PROFIT_MARKET"
    assert sl["params"]["stopPrice"] == 99000.0
    assert tp["params"]["stopPrice"] == 101000.0
    assert sl["params"]["workingType"] == "CONTRACT_PRICE"
    assert tp["params"]["workingType"] == "CONTRACT_PRICE"
    assert sl["params"]["reduceOnly"] is True
    assert tp["params"]["reduceOnly"] is True
    assert sl["params"]["newClientOrderId"] == "abc_1"
    assert tp["params"]["newClientOrderId"] == "abc_2"

