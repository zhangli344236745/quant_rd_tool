from __future__ import annotations

import json
from pathlib import Path

from quant_rd_tool.crypto_polymarket_scanner import (
    MarketFilterConfig,
    filter_markets,
    passes_market_filter,
    walk_ask_ladder,
    walk_binary_ask_depth,
)


def test_passes_market_filter_rejects_updown_slug():
    cfg = MarketFilterConfig(min_volume24hr_usd=1000, exclude_slug_patterns=["*-updown-*"])
    m = {"slug": "eth-updown-5m-123", "volume24hr": 99999, "acceptingOrders": True}
    assert passes_market_filter(m, cfg) is False


def test_passes_market_filter_accepts_normal_market():
    cfg = MarketFilterConfig(min_volume24hr_usd=5000)
    m = {"slug": "btc-100k-2026", "volume24hr": 50000, "acceptingOrders": True}
    assert passes_market_filter(m, cfg) is True


def test_watchlist_bypasses_volume_filter():
    cfg = MarketFilterConfig(min_volume24hr_usd=5000)
    m = {"condition_id": "c-watch", "slug": "low-vol", "volume24hr": 10, "acceptingOrders": True}
    assert passes_market_filter(m, cfg, watchlist_ids={"c-watch"}) is True


def test_filter_markets_counts_skipped():
    cfg = MarketFilterConfig(min_volume24hr_usd=5000)
    markets = [
        {"slug": "good", "volume24hr": 6000, "acceptingOrders": True},
        {"slug": "eth-updown-5m-x", "volume24hr": 90000, "acceptingOrders": True},
    ]
    kept, skipped = filter_markets(markets, cfg)
    assert len(kept) == 1
    assert skipped == 1


def test_walk_ask_ladder_vwap():
    book = json.loads(
        (Path(__file__).parent / "fixtures" / "polymarket_clob_book_deep.json").read_text()
    )
    r = walk_ask_ladder(book, target_shares=100, max_levels=10)
    assert r["filled_shares"] == 100
    assert 0.45 < r["vwap"] < 0.48
    assert len(r["ladder"]) >= 2


def test_walk_binary_ask_depth():
    book = json.loads(
        (Path(__file__).parent / "fixtures" / "polymarket_clob_book_deep.json").read_text()
    )
    r = walk_binary_ask_depth(book, book, target_shares=100, max_levels=10)
    assert r["fillable_shares"] == 100
    assert r["vwap_yes"] > 0
