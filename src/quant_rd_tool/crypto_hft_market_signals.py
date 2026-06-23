"""Market microstructure signals for crypto market-making strategies."""

from __future__ import annotations

import math
from typing import Any


def update_mid_history(
    state: dict[str, Any],
    mid: float,
    *,
    max_samples: int = 60,
) -> list[float]:
    """Append mid to rolling history stored in bot state."""
    if mid <= 0:
        return list(state.get("mid_history") or [])
    hist: list[float] = list(state.get("mid_history") or [])
    hist.append(float(mid))
    if len(hist) > max_samples:
        hist = hist[-max_samples:]
    state["mid_history"] = hist
    return hist


def realized_vol_bps(history: list[float], *, min_samples: int = 5) -> float:
    """Annualized-ish volatility proxy in bps from mid price history."""
    if len(history) < min_samples:
        return 0.0
    rets: list[float] = []
    for i in range(1, len(history)):
        prev, cur = history[i - 1], history[i]
        if prev > 0 and cur > 0:
            rets.append(math.log(cur / prev))
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    stdev = math.sqrt(max(var, 0.0))
    # Scale log-return stdev to bps (per tick); cap for stability.
    return min(stdev * 10_000.0 * math.sqrt(len(rets)), 500.0)


def book_imbalance(book: dict[str, Any], *, depth: int = 5) -> float:
    """Order-book volume imbalance in [-1, 1] (bid-heavy positive)."""
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    n = max(int(depth), 1)
    bid_vol = sum(float(b[1]) for b in bids[:n])
    ask_vol = sum(float(a[1]) for a in asks[:n])
    total = bid_vol + ask_vol
    if total <= 0:
        return 0.0
    return max(-1.0, min(1.0, (bid_vol - ask_vol) / total))


def imbalance_shift_bps(imbalance: float, max_skew_bps: float) -> float:
    """Convert imbalance to quote shift in bps (shift reservation price)."""
    return float(imbalance) * float(max_skew_bps)
