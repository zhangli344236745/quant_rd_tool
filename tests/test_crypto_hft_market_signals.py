from __future__ import annotations

from quant_rd_tool.crypto_hft_market_signals import book_imbalance, realized_vol_bps, update_mid_history


def test_update_mid_history_caps():
    state: dict = {}
    for i in range(10):
        update_mid_history(state, float(100 + i), max_samples=5)
    assert len(state["mid_history"]) == 5
    assert state["mid_history"][-1] == 109.0


def test_realized_vol_positive_with_moves():
    hist = [100.0, 101.0, 99.0, 102.0, 98.0, 103.0]
    vol = realized_vol_bps(hist)
    assert vol > 0


def test_book_imbalance_symmetric():
    book = {"bids": [[1, 10]], "asks": [[1.01, 10]]}
    assert book_imbalance(book) == 0.0
