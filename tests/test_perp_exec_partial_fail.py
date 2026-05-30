from __future__ import annotations

from dataclasses import dataclass

import pytest

from quant_rd_tool.perp_exec import NativeProtectionParams, try_place_native_sl_tp


@dataclass
class _Call:
    symbol: str
    type: str
    side: str
    amount: float
    params: dict


class FakeExchange:
    def __init__(self, *, fail_on: int) -> None:
        self.calls: list[_Call] = []
        self._fail_on = fail_on

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        idx = len(self.calls) + 1
        params = params or {}
        self.calls.append(_Call(symbol=symbol, type=type, side=side, amount=amount, params=params))
        if idx == self._fail_on:
            raise RuntimeError("boom")
        return {"id": f"ex_{idx}", "symbol": symbol, "type": type, "side": side, "amount": amount}


def test_partial_fail_returns_error_and_no_tp_ref():
    ex = FakeExchange(fail_on=2)  # fail TP
    p = NativeProtectionParams(
        symbol="BTC/USDT:USDT",
        amount=0.01,
        sl_stop_price=99000.0,
        tp_stop_price=101000.0,
        working_type="CONTRACT_PRICE",
        sl_client_order_id="cid_sl",
        tp_client_order_id="cid_tp",
    )
    out = try_place_native_sl_tp(ex, p, position_side="long")
    assert out["ok"] is False
    assert out["sl"] is not None
    assert out["tp"] is None
    assert "boom" in (out["error"] or "")


def test_full_fail_returns_no_refs():
    ex = FakeExchange(fail_on=1)  # fail SL first
    p = NativeProtectionParams(
        symbol="BTC/USDT:USDT",
        amount=0.01,
        sl_stop_price=99000.0,
        tp_stop_price=101000.0,
        working_type="CONTRACT_PRICE",
        sl_client_order_id="cid_sl",
        tp_client_order_id="cid_tp",
    )
    out = try_place_native_sl_tp(ex, p, position_side="long")
    assert out["ok"] is False
    assert out["sl"] is None
    assert out["tp"] is None

