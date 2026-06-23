from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_rd_tool.crypto_hft_market_signals import book_imbalance, realized_vol_bps, update_mid_history
from quant_rd_tool.crypto_hft_strategies import build_quotes, list_strategies


def _book() -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "hft_book.json").read_text())


def test_list_strategies():
    ids = {s["id"] for s in list_strategies()}
    assert ids == {"classic_mm", "grid_mm", "vol_mm", "imbalance_mm", "as_mm"}


def test_classic_mm_quotes_both_sides():
    quotes = build_quotes("classic_mm", _book(), inventory_usdt=0)
    sides = {q.side for q in quotes}
    assert sides == {"buy", "sell"}


def test_classic_mm_multi_level():
    quotes = build_quotes("classic_mm", _book(), inventory_usdt=0, params={"levels": 3})
    assert len([q for q in quotes if q.side == "buy"]) == 3


def test_classic_mm_skew_long_inventory():
    flat = build_quotes("classic_mm", _book(), inventory_usdt=0)
    long = build_quotes("classic_mm", _book(), inventory_usdt=400)
    bid_flat = next(q for q in flat if q.side == "buy")
    bid_long = next(q for q in long if q.side == "buy")
    assert bid_long.price <= bid_flat.price


def test_grid_mm_multiple_levels():
    quotes = build_quotes("grid_mm", _book(), inventory_usdt=0, params={"grid_levels": 3})
    assert len([q for q in quotes if q.side == "buy"]) == 3
    assert len([q for q in quotes if q.side == "sell"]) == 3


def test_vol_mm_widens_with_history():
    state: dict = {}
    book = _book()
    for px in [100.0, 100.5, 99.5, 101.0, 98.5, 102.0]:
        b = {"bids": [[px - 0.05, 1]], "asks": [[px + 0.05, 1]]}
        update_mid_history(state, px)
    low_vol = build_quotes("vol_mm", book, inventory_usdt=0, state=state, params={"vol_sensitivity": 0})
    high_vol = build_quotes("vol_mm", book, inventory_usdt=0, state=state, params={"vol_sensitivity": 1.0})
    low_spread = next(q for q in low_vol if q.side == "sell").price - next(q for q in low_vol if q.side == "buy").price
    high_spread = next(q for q in high_vol if q.side == "sell").price - next(q for q in high_vol if q.side == "buy").price
    assert high_spread >= low_spread


def test_imbalance_mm_shifts_with_book():
    book = _book()
    bid_heavy = {
        "bids": [[100.0, 50], [99.9, 40]],
        "asks": [[100.1, 1], [100.2, 1]],
    }
    ask_heavy = {
        "bids": [[100.0, 1], [99.9, 1]],
        "asks": [[100.1, 50], [100.2, 40]],
    }
    q_bid = build_quotes("imbalance_mm", bid_heavy, inventory_usdt=0)
    q_ask = build_quotes("imbalance_mm", ask_heavy, inventory_usdt=0)
    mid_bid = (next(q for q in q_bid if q.side == "buy").price + next(q for q in q_bid if q.side == "sell").price) / 2
    mid_ask = (next(q for q in q_ask if q.side == "buy").price + next(q for q in q_ask if q.side == "sell").price) / 2
    assert mid_bid > mid_ask


def test_as_mm_quotes_both_sides():
    state: dict = {"mid_history": [100.0, 100.2, 99.8, 100.1]}
    quotes = build_quotes("as_mm", _book(), inventory_usdt=50, state=state)
    assert {q.side for q in quotes} == {"buy", "sell"}


def test_book_imbalance_range():
    imb = book_imbalance(_book())
    assert -1.0 <= imb <= 1.0


def test_realized_vol_bps_zero_short_history():
    assert realized_vol_bps([100.0, 100.1]) == 0.0
