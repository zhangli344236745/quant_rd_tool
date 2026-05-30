from __future__ import annotations

from dataclasses import dataclass

from quant_rd_tool.perp_exec import NativeProtectionParams, place_native_sl_tp


@dataclass
class _Call:
    symbol: str
    type: str
    side: str
    amount: float
    price: float | None
    params: dict


class FakeExchange:
    def __init__(self) -> None:
        self.calls: list[_Call] = []

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        params = params or {}
        self.calls.append(_Call(symbol=symbol, type=type, side=side, amount=amount, price=price, params=params))
        # mimic ccxt response shape minimally
        return {"id": f"ex_{len(self.calls)}", "symbol": symbol, "type": type, "side": side, "amount": amount}


def test_place_native_sl_tp_uses_stop_price_and_working_type():
    ex = FakeExchange()
    p = NativeProtectionParams(
        symbol="BTC/USDT:USDT",
        amount=0.01,
        sl_stop_price=99000.0,
        tp_stop_price=101000.0,
        working_type="CONTRACT_PRICE",
        sl_client_order_id="cid_sl",
        tp_client_order_id="cid_tp",
    )
    sl_ref, tp_ref = place_native_sl_tp(ex, p, position_side="long")
    assert sl_ref.exchange_order_id == "ex_1"
    assert tp_ref.exchange_order_id == "ex_2"
    assert ex.calls[0].type == "STOP_MARKET"
    assert ex.calls[1].type == "TAKE_PROFIT_MARKET"
    assert ex.calls[0].params["stopPrice"] == 99000.0
    assert ex.calls[1].params["stopPrice"] == 101000.0
    assert ex.calls[0].params["workingType"] == "CONTRACT_PRICE"
    assert ex.calls[1].params["workingType"] == "CONTRACT_PRICE"
    assert ex.calls[0].params["reduceOnly"] is True
    assert ex.calls[1].params["reduceOnly"] is True
    assert ex.calls[0].params["newClientOrderId"] == "cid_sl"
    assert ex.calls[1].params["newClientOrderId"] == "cid_tp"

