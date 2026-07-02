from __future__ import annotations

import json

from quant_rd_tool.crypto_polymarket_cross_venue import (
    compare_implied_prob,
    detect_bases_in_scan,
    find_cross_venue_pairs,
    match_crypto_pair,
)


def test_compare_implied_prob():
    r = compare_implied_prob(0.62, 0.58)
    assert r["prob_spread_bps"] == 400.0


def test_match_crypto_pair():
    poly = {
        "condition_id": "c1",
        "question": "Will Bitcoin reach 100k in 2026?",
        "implied_prob_yes": 0.55,
    }
    kalshi = [
        {"ticker": "KXBTC-26", "title": "Bitcoin above 100k in 2026?", "implied_prob_yes": 0.52},
        {"ticker": "OTHER", "title": "Rain in Seattle", "implied_prob_yes": 0.5},
    ]
    pair = match_crypto_pair(poly, kalshi, keywords=["bitcoin", "btc", "100k"], threshold=0.5)
    assert pair is not None
    assert pair["kalshi"]["ticker"] == "KXBTC-26"


def test_detect_bases_in_scan():
    items = [
        {"question": "Will Bitcoin hit 120k?", "slug": "btc-120k"},
        {"question": "Ethereum ETF flows", "slug": "eth-etf"},
    ]
    bases = detect_bases_in_scan(items)
    assert "BTC" in bases
    assert "ETH" in bases


def test_find_cross_venue_pairs_sets_base():
    poly = [{"condition_id": "c1", "question": "Bitcoin price?", "implied_prob_yes": 0.6}]
    kalshi = [{"ticker": "KXBTC", "title": "Bitcoin price above?", "implied_prob_yes": 0.55}]
    pairs = find_cross_venue_pairs("BTC", poly, kalshi, keywords=["bitcoin", "btc"], threshold=0.3)
    assert pairs
    assert pairs[0]["base"] == "BTC"


def test_load_cross_venue_history(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    path = tmp_path / "cross_venue_history.jsonl"
    path.write_text(
        json.dumps({"ts": datetime.now(UTC).isoformat(), "base": "BTC", "prob_spread_bps": 50})
        + "\n",
        encoding="utf-8",
    )
    from quant_rd_tool.crypto_polymarket_cross_venue import load_cross_venue_history

    rows = load_cross_venue_history(hours=168)
    assert len(rows) == 1
    assert rows[0]["base"] == "BTC"
