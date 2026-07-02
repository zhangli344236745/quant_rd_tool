"""Match crypto symbols to Polymarket prediction markets and implied probabilities."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

CRYPTO_SYMBOL_KEYWORDS: dict[str, list[str]] = {
    "BTC": ["bitcoin", "btc", "100k", "150k", "halving"],
    "ETH": ["ethereum", "eth", "etf"],
    "SOL": ["solana", "sol"],
    "BNB": ["bnb", "binance"],
}


def base_asset(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s.startswith("CRYPTO_"):
        return s.replace("CRYPTO_", "", 1)
    if "/" in s:
        return s.split("/")[0]
    if s.endswith("USDT"):
        return s[: -len("USDT")]
    return s


def keywords_for_symbol(symbol: str, overrides: dict[str, list[str]] | None = None) -> list[str]:
    base = base_asset(symbol)
    if overrides and base in overrides:
        return [str(x).lower() for x in overrides[base]]
    return list(CRYPTO_SYMBOL_KEYWORDS.get(base, [base.lower()]))


def score_market_relevance(market: dict[str, Any], keywords: list[str]) -> float:
    text = " ".join(
        str(market.get(k) or "")
        for k in ("question", "slug", "title")
    ).lower()
    if not text.strip():
        return 0.0
    hits = sum(1 for kw in keywords if kw and kw.lower() in text)
    if hits == 0:
        return 0.0
    vol = float(market.get("volume24hr") or 0)
    vol_bonus = min(vol / 100_000.0, 1.0) * 0.3
    return hits * 0.5 + vol_bonus


def implied_prob_from_book(book: dict[str, Any] | None) -> float | None:
    if not book:
        return None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    try:
        best_bid = max(float(b["price"]) for b in bids) if bids else 0.0
        best_ask = min(float(a["price"]) for a in asks) if asks else 1.0
    except (KeyError, TypeError, ValueError):
        return None
    if best_bid > 0 and best_ask <= 1:
        return round((best_bid + best_ask) / 2.0, 4)
    if 0 < best_ask < 1:
        return round(best_ask, 4)
    if best_bid > 0:
        return round(best_bid, 4)
    return None


def _market_summary(
    market: dict[str, Any],
    *,
    implied_prob_yes: float | None,
    score: float,
) -> dict[str, Any]:
    return {
        "condition_id": market.get("condition_id"),
        "question": market.get("question"),
        "slug": market.get("slug"),
        "volume24hr": market.get("volume24hr"),
        "market_url": market.get("market_url"),
        "implied_prob_yes": implied_prob_yes,
        "relevance_score": round(score, 4),
        "end_date": market.get("end_date") or market.get("endDate"),
    }


def _arb_summary_from_scan(items: list[dict[str, Any]], condition_ids: set[str]) -> dict[str, Any]:
    hits = [r for r in items if r.get("opportunity") and str(r.get("condition_id") or "") in condition_ids]
    best = max(
        (float(r.get("edge_at_size_bps") or r.get("edge_bps") or 0) for r in hits),
        default=0.0,
    )
    by_st: dict[str, int] = {}
    for r in hits:
        st = str(r.get("strategy_type") or "binary_ask")
        by_st[st] = by_st.get(st, 0) + 1
    return {
        "opportunity_hits": len(hits),
        "best_edge_bps": round(best, 2) if hits else None,
        "strategy_counts": by_st,
    }


def fetch_polymarket_context(
    symbol: str,
    *,
    data_dir: str = "data/crypto",
    max_markets: int = 5,
    include_arb_summary: bool = True,
    http_get: Any = None,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_polymarket_arb import (
        fetch_clob_book,
        fetch_gamma_markets,
        load_config,
        load_latest_scan,
        normalize_gamma_market,
    )

    base = base_asset(symbol)
    cfg = load_config()
    kw_overrides = getattr(cfg, "crypto_symbol_keywords", None) or {}
    keywords = keywords_for_symbol(base, kw_overrides if isinstance(kw_overrides, dict) else None)

    if not keywords:
        return {"enabled": False, "base": base, "error": "no keywords for symbol"}

    scored: dict[str, tuple[float, dict[str, Any]]] = {}

    latest = load_latest_scan()
    for row in (latest or {}).get("items") or []:
        m = {
            "condition_id": row.get("condition_id"),
            "question": row.get("question"),
            "slug": row.get("slug"),
            "volume24hr": row.get("volume24hr"),
            "market_url": row.get("market_url"),
            "yes_token_id": row.get("yes_token_id"),
            "ask_yes": row.get("ask_yes"),
            "bid_yes": row.get("bid_yes"),
        }
        sc = score_market_relevance(m, keywords)
        if sc > 0:
            cid = str(m.get("condition_id") or "")
            prev = scored.get(cid)
            if not prev or sc > prev[0]:
                scored[cid] = (sc, m)

    try:
        gamma_rows = fetch_gamma_markets(limit=150, http_get=http_get, use_cache=True)
        for gm in gamma_rows:
            sc = score_market_relevance(gm, keywords)
            if sc <= 0:
                continue
            cid = str(gm.get("condition_id") or "")
            prev = scored.get(cid)
            if not prev or sc > prev[0]:
                scored[cid] = (sc, gm)
    except Exception as e:  # noqa: BLE001
        logger.warning("gamma fetch for polymarket context %s: %s", base, e)

    if not scored:
        return {
            "enabled": False,
            "base": base,
            "keywords": keywords,
            "error": "no matching Polymarket markets",
        }

    ranked = sorted(scored.values(), key=lambda x: x[0], reverse=True)[:max_markets]
    markets_out: list[dict[str, Any]] = []
    for sc, m in ranked:
        prob: float | None = None
        if m.get("ask_yes") is not None and m.get("bid_yes") is not None:
            try:
                prob = round((float(m["bid_yes"]) + float(m["ask_yes"])) / 2.0, 4)
            except (TypeError, ValueError):
                prob = None
        if prob is None and m.get("yes_token_id"):
            try:
                book = fetch_clob_book(str(m["yes_token_id"]), http_get=http_get)
                prob = implied_prob_from_book(book)
            except Exception:  # noqa: BLE001
                prob = None
        markets_out.append(_market_summary(m, implied_prob_yes=prob, score=sc))

    top = markets_out[0]
    cid_set = {str(x.get("condition_id") or "") for x in markets_out}
    arb = (
        _arb_summary_from_scan((latest or {}).get("items") or [], cid_set)
        if include_arb_summary and latest
        else {}
    )

    return {
        "enabled": True,
        "base": base,
        "keywords": keywords,
        "market_count": len(markets_out),
        "top_market": top,
        "markets": markets_out,
        "arb_summary": arb,
        "scanned_at": (latest or {}).get("scanned_at"),
    }
