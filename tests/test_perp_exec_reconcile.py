from __future__ import annotations

from dataclasses import dataclass

from quant_rd_tool.perp_exec import NativeProtectionParams, reconcile_native_protection
from quant_rd_tool.perp_state import OrderRef, PerpSymbolState


@dataclass
class _Call:
    kind: str
    args: tuple
    kwargs: dict


class FakeExchange:
    def __init__(self, open_order_ids: set[str]) -> None:
        self._open_order_ids = set(open_order_ids)
        self.calls: list[_Call] = []
        self._order_seq = 0

    def fetch_open_orders(self, symbol=None, since=None, limit=None, params=None):
        # Return minimal ccxt orders with ids
        return [{"id": oid, "symbol": symbol} for oid in sorted(self._open_order_ids)]

    def cancel_order(self, id, symbol=None, params=None):
        self.calls.append(_Call("cancel_order", (id, symbol), {"params": params or {}}))
        self._open_order_ids.discard(id)
        return {"id": id, "status": "canceled"}

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.calls.append(_Call("create_order", (symbol, type, side, amount, price), {"params": params or {}}))
        self._order_seq += 1
        oid = f"new_{self._order_seq}"
        self._open_order_ids.add(oid)
        return {"id": oid, "symbol": symbol, "type": type, "side": side, "amount": amount}


def test_reconcile_cancels_stale_on_flat():
    ex = FakeExchange(open_order_ids={"sl1", "tp1"})
    st = PerpSymbolState(
        symbol="BTC/USDT:USDT",
        sl_order=OrderRef(exchange_order_id="sl1"),
        tp_order=OrderRef(exchange_order_id="tp1"),
    )
    reconcile_native_protection(ex, st, position_side="flat", desired=None)
    assert any(c.kind == "cancel_order" and c.args[0] == "sl1" for c in ex.calls)
    assert any(c.kind == "cancel_order" and c.args[0] == "tp1" for c in ex.calls)


def test_reconcile_replaces_missing_tp_when_open():
    # Exchange shows only SL open; TP missing -> should create TP
    ex = FakeExchange(open_order_ids={"sl1"})
    st = PerpSymbolState(
        symbol="BTC/USDT:USDT",
        sl_order=OrderRef(exchange_order_id="sl1"),
        tp_order=OrderRef(exchange_order_id="tp1"),
    )
    desired = NativeProtectionParams(
        symbol="BTC/USDT:USDT",
        amount=0.01,
        sl_stop_price=99000.0,
        tp_stop_price=101000.0,
        working_type="CONTRACT_PRICE",
        sl_client_order_id="cid_sl",
        tp_client_order_id="cid_tp",
    )
    reconcile_native_protection(ex, st, position_side="long", desired=desired)
    assert any(c.kind == "create_order" and c.args[1] == "TAKE_PROFIT_MARKET" for c in ex.calls)

