from __future__ import annotations

from quant_rd_tool.crypto_news_scoring import rank_candidates, score_news_item


def test_fed_raises_rates_scores_macro():
    item = {
        "title": "Fed raises rates",
        "summary": "The Federal Reserve increased interest rates amid inflation concerns.",
    }
    scored = score_news_item(item)
    assert scored["score"] >= 40
    assert scored["category"] == "macro"
    assert scored["impact_direction"] in ("bearish", "neutral", "mixed", "bullish")


def test_btc_mention_boost():
    base = {
        "title": "SEC approves new ETF framework",
        "summary": "Regulatory clarity improves for digital assets.",
    }
    without = score_news_item(base)
    with_btc = score_news_item({**base, "title": "SEC approves BTC ETF framework"})
    assert with_btc["score"] > without["score"]
    assert "BTC" in with_btc.get("symbols", [])


def test_neutral_item_below_threshold():
    item = {
        "title": "Local community picnic planned",
        "summary": "Families gather in the park this weekend.",
    }
    scored = score_news_item(item)
    assert scored["score"] < 40
    assert scored["category"] == "market"


def test_rank_candidates_filters_and_sorts():
    items = [
        {"title": "Fed hikes rates", "summary": "macro inflation", "score": 55, "category": "macro"},
        {"title": "Weather", "summary": "sunny", "score": 10, "category": "market"},
        {"title": "SEC sues exchange", "summary": "enforcement regulation", "score": 45, "category": "regulation"},
    ]
    ranked = rank_candidates(items, min_score=40, top_n=2)
    assert len(ranked) == 2
    assert ranked[0]["score"] >= ranked[1]["score"]
    assert all(r["score"] >= 40 for r in ranked)
