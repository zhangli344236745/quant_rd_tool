from __future__ import annotations

import json
from pathlib import Path

from quant_rd_tool.crypto_hft_execution import (
    client_order_id,
    plan_reconcile_tagged,
    prepare_quotes,
)
from quant_rd_tool.crypto_hft_strategies import Quote


def test_client_order_id_stable():
    cid = client_order_id("btc-mm", "classic_bid")
    assert cid.startswith("mm-btc-mm-")
    assert len(cid) <= 36


def test_prepare_quotes_rejects_crossing():
    book = json.loads((Path(__file__).parent / "fixtures" / "hft_book.json").read_text())
    quotes = [Quote(side="buy", price=100.2, amount=0.1, tag="classic_bid")]
    out, stats = prepare_quotes(quotes, book, maker_fee_bps=2, min_edge_bps=1)
    assert stats.rejected_cross == 1
    assert out == []


def test_prepare_quotes_fee_widen():
    book = json.loads((Path(__file__).parent / "fixtures" / "hft_book.json").read_text())
    quotes = [Quote(side="buy", price=100.04, amount=0.1, tag="classic_bid")]
    out, stats = prepare_quotes(quotes, book, maker_fee_bps=2, min_edge_bps=1)
    assert len(out) == 1
    assert out[0].price < 100.04
    assert stats.fee_adjusted == 1


def test_plan_reconcile_tagged_by_client_id():
    desired = [Quote(side="buy", price=100.0, amount=0.1, tag="classic_bid")]
    cid = client_order_id("bot1", "classic_bid")
    open_orders = [{"id": "1", "side": "buy", "price": 99.0, "clientOrderId": cid}]
    plan = plan_reconcile_tagged(
        open_orders, desired, tolerance_bps=3, bot_id="bot1", use_tags=True
    )
    assert len(plan.cancel) == 0
    assert len(plan.place) == 0
