from __future__ import annotations

import json
from pathlib import Path

from quant_rd_tool.crypto_hft_common import plan_reconcile, price_within_tolerance, summarize_book
from quant_rd_tool.crypto_hft_strategies import Quote


def test_price_within_tolerance():
    assert price_within_tolerance(100.0, 100.02, 3.0)
    assert not price_within_tolerance(100.0, 100.1, 3.0)


def test_plan_reconcile_cancel_stale():
    desired = [Quote(side="buy", price=100.0, amount=0.1)]
    open_orders = [{"id": "1", "side": "buy", "price": 99.0}]
    plan = plan_reconcile(open_orders, desired, tolerance_bps=3)
    assert len(plan.cancel) == 1
    assert len(plan.place) == 1


def test_plan_reconcile_keep_matching():
    desired = [Quote(side="buy", price=100.0, amount=0.1)]
    open_orders = [{"id": "1", "side": "buy", "price": 100.01}]
    plan = plan_reconcile(open_orders, desired, tolerance_bps=5)
    assert len(plan.cancel) == 0
    assert len(plan.place) == 0


def test_summarize_book():
    book = json.loads((Path(__file__).parent / "fixtures" / "hft_book.json").read_text())
    s = summarize_book(book)
    assert s["mid"] == 100.05
    assert s["spread_bps"] is not None
