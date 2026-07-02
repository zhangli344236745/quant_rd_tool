from __future__ import annotations

from quant_rd_tool.crypto_polymarket_context import (
    implied_prob_from_book,
    score_market_relevance,
    keywords_for_symbol,
)
from quant_rd_tool.crypto_polymarket_integration import (
    prediction_stance_from_prob,
    synthesize_prediction_cross_view,
)


def test_score_market_relevance_btc():
    m = {"question": "Will Bitcoin hit 100k?", "slug": "btc-100k", "volume24hr": 50000}
    sc = score_market_relevance(m, keywords_for_symbol("BTC"))
    assert sc > 0


def test_implied_prob_from_book():
    book = {"bids": [{"price": "0.44", "size": "10"}], "asks": [{"price": "0.46", "size": "10"}]}
    assert implied_prob_from_book(book) == 0.45


def test_cross_view_resonance():
    pm = {
        "enabled": True,
        "base": "BTC",
        "market_count": 1,
        "top_market": {"question": "BTC 100k?", "implied_prob_yes": 0.65},
        "arb_summary": {},
    }
    cross = synthesize_prediction_cross_view(spot_stance="看涨", spot_action="buy", pm_ctx=pm)
    assert cross["alignment"] == "共振"
    assert prediction_stance_from_prob(0.65) == "偏多"
