"""Kalshi public market data (read-only, crypto-themed filter)."""

from __future__ import annotations

import logging
from typing import Any, Callable

import httpx

from quant_rd_tool.crypto_polymarket_context import keywords_for_symbol, score_market_relevance

logger = logging.getLogger(__name__)

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
HTTP_TIMEOUT = 10.0
HttpGet = Callable[[str, dict[str, Any] | None], Any]


def _default_http_get(url: str, params: dict[str, Any] | None = None) -> Any:
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        r = client.get(url, params=params or {})
        r.raise_for_status()
        return r.json()


def normalize_kalshi_market(raw: dict[str, Any]) -> dict[str, Any]:
    ticker = str(raw.get("ticker") or "")
    title = str(raw.get("title") or raw.get("subtitle") or ticker)
    yes_bid = raw.get("yes_bid_dollars") or raw.get("yes_bid")
    yes_ask = raw.get("yes_ask_dollars") or raw.get("yes_ask")
    try:
        bid = float(yes_bid) if yes_bid is not None else None
        ask = float(yes_ask) if yes_ask is not None else None
    except (TypeError, ValueError):
        bid, ask = None, None
    prob: float | None = None
    if bid is not None and ask is not None:
        prob = round((bid + ask) / 2.0, 4)
    elif ask is not None:
        prob = round(ask, 4)
    elif bid is not None:
        prob = round(bid, 4)
    return {
        "ticker": ticker,
        "title": title,
        "subtitle": raw.get("subtitle"),
        "status": raw.get("status"),
        "yes_bid": bid,
        "yes_ask": ask,
        "implied_prob_yes": prob,
        "volume": raw.get("volume") or raw.get("volume_fp"),
        "event_ticker": raw.get("event_ticker"),
    }


def fetch_kalshi_markets(
    *,
    limit: int = 200,
    status: str = "open",
    http_get: HttpGet | None = None,
) -> list[dict[str, Any]]:
    getter = http_get or _default_http_get
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    pages = 0
    while len(out) < limit and pages < 5:
        params: dict[str, Any] = {"limit": min(200, limit - len(out)), "status": status}
        if cursor:
            params["cursor"] = cursor
        try:
            data = getter(f"{KALSHI_API}/markets", params)
        except Exception as e:  # noqa: BLE001
            logger.warning("kalshi markets fetch: %s", e)
            break
        markets = data.get("markets") or []
        for raw in markets:
            out.append(normalize_kalshi_market(raw))
        cursor = data.get("cursor") or None
        pages += 1
        if not cursor or not markets:
            break
    return out[:limit]


def fetch_crypto_markets(
    base: str,
    *,
    limit: int = 50,
    keyword_overrides: dict[str, list[str]] | None = None,
    http_get: HttpGet | None = None,
) -> list[dict[str, Any]]:
    keywords = keywords_for_symbol(base, keyword_overrides)
    all_markets = fetch_kalshi_markets(limit=300, http_get=http_get)
    scored: list[tuple[float, dict[str, Any]]] = []
    for m in all_markets:
        text_market = {"question": m.get("title"), "slug": m.get("subtitle") or ""}
        sc = score_market_relevance(text_market, keywords)
        if sc > 0:
            m["relevance_score"] = round(sc, 4)
            m["base"] = base.upper()
            scored.append((sc, m))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:limit]]


def fetch_orderbook(ticker: str, *, http_get: HttpGet | None = None) -> dict[str, Any]:
    getter = http_get or _default_http_get
    return getter(f"{KALSHI_API}/markets/{ticker}/orderbook", None)
