from __future__ import annotations

from quant_rd_tool.crypto_polymarket_arb import PolymarketArbConfig
from quant_rd_tool.crypto_polymarket_strategies import (
    eval_binary_ask,
    eval_binary_bid,
    eval_multi_ask,
)


def test_eval_binary_ask_depth_lower_than_top():
    cfg = PolymarketArbConfig(taker_fee_bps=200, min_liquidity_usd=50.0, use_depth_for_opportunity=True)
    top = eval_binary_ask(
        ask_yes=0.45,
        ask_no=0.50,
        ask_yes_size=200,
        ask_no_size=200,
        depth=None,
        config=cfg,
    )
    depth = {
        "vwap_yes": 0.46,
        "vwap_no": 0.51,
        "fillable_shares": 100,
        "depth_levels": 2,
        "yes_ladder": [],
        "no_ladder": [],
    }
    deep = eval_binary_ask(
        ask_yes=0.45,
        ask_no=0.50,
        ask_yes_size=200,
        ask_no_size=200,
        depth=depth,
        config=cfg,
    )
    assert deep["edge_at_size_bps"] < top["edge_bps"]
    assert deep["slippage_bps"] < 0


def test_eval_binary_bid_positive():
    cfg = PolymarketArbConfig(taker_fee_bps=200, min_liquidity_usd=50.0, min_edge_bps=10)
    r = eval_binary_bid(
        bid_yes=0.55,
        bid_no=0.50,
        bid_yes_size=100,
        bid_no_size=100,
        depth=None,
        config=cfg,
    )
    assert r["edge_bps"] > 0
    assert r["paper_tradable"] is False


def test_eval_multi_ask():
    cfg = PolymarketArbConfig(taker_fee_bps=200, min_liquidity_usd=50.0, min_outcomes_multi=3)
    r = eval_multi_ask(
        vwaps=[0.30, 0.30, 0.30],
        sizes=[100, 100, 100],
        outcomes=["A", "B", "C"],
        depth=None,
        config=cfg,
    )
    assert r["edge_bps"] > 0
    assert r["strategy_type"] == "multi_ask"
