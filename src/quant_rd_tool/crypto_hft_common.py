"""Shared quote reconciliation helpers for crypto market-making modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_hft_strategies import Quote

MarketType = Literal["spot", "future"]


@dataclass
class ReconcilePlan:
    cancel: list[dict[str, Any]]
    place: list[Quote]


def resolve_ccxt_symbol(
    *,
    symbol: str,
    quote: str,
    market_type: MarketType,
) -> str:
    base = symbol.strip().upper()
    q = quote.strip().upper()
    if market_type == "future":
        return f"{base}/{q}:{q}"
    return cxt.to_ccxt_symbol(base, q)


def summarize_book(book: dict[str, Any]) -> dict[str, Any]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return {"best_bid": None, "best_ask": None, "mid": None, "spread_bps": None}
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 10_000 if mid > 0 else None
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_bps": spread_bps,
        "bids": bids[:5],
        "asks": asks[:5],
    }


def price_within_tolerance(existing: float, target: float, tolerance_bps: float) -> bool:
    if existing <= 0 or target <= 0:
        return False
    diff_bps = abs(existing - target) / target * 10_000
    return diff_bps <= tolerance_bps


def plan_reconcile(
    open_orders: list[dict[str, Any]],
    desired: list[Quote],
    *,
    tolerance_bps: float,
) -> ReconcilePlan:
    unmatched_open = list(open_orders)
    to_place: list[Quote] = []
    to_cancel: list[dict[str, Any]] = []

    for quote in desired:
        match = None
        for o in unmatched_open:
            if str(o.get("side", "")).lower() != quote.side:
                continue
            px = float(o.get("price") or 0)
            if price_within_tolerance(px, quote.price, tolerance_bps):
                match = o
                break
        if match:
            unmatched_open.remove(match)
        else:
            to_place.append(quote)

    to_cancel.extend(unmatched_open)
    return ReconcilePlan(cancel=to_cancel, place=to_place)
