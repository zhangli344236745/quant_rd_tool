"""Polymarket Gamma filter, CLOB book fetch, and order-book depth walks."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Literal

import httpx

BookStatus = Literal["ok", "no_book", "incomplete", "error"]
HttpGet = Callable[[str, dict[str, Any] | None], Any]

CLOB_API = "https://clob.polymarket.com"


@dataclass
class MarketFilterConfig:
    min_volume24hr_usd: float = 5000.0
    exclude_slug_patterns: list[str] = field(
        default_factory=lambda: ["*-updown-*", "*-5m-*"]
    )
    require_accepting_orders: bool = True


def passes_market_filter(
    market: dict[str, Any],
    cfg: MarketFilterConfig,
    *,
    watchlist_ids: set[str] | None = None,
) -> bool:
    cid = str(market.get("condition_id") or "")
    on_watchlist = bool(watchlist_ids and cid in watchlist_ids)
    slug = str(market.get("slug") or "")
    for pat in cfg.exclude_slug_patterns:
        if fnmatch(slug, pat):
            return False
    if not on_watchlist:
        vol = float(market.get("volume24hr") or 0)
        if vol < cfg.min_volume24hr_usd:
            return False
    if cfg.require_accepting_orders:
        accepting = market.get("acceptingOrders", market.get("accepting_orders"))
        if accepting is False:
            return False
    return True


def filter_markets(
    markets: list[dict[str, Any]],
    cfg: MarketFilterConfig,
    *,
    watchlist_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    skipped = 0
    for m in markets:
        if passes_market_filter(m, cfg, watchlist_ids=watchlist_ids):
            kept.append(m)
        else:
            skipped += 1
    return kept, skipped


def classify_book_error(exc: Exception) -> BookStatus:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return "no_book"
    return "error"


def fetch_clob_book_safe(
    token_id: str,
    *,
    http_get: HttpGet,
) -> dict[str, Any]:
    try:
        book = http_get(f"{CLOB_API}/book", {"token_id": token_id})
        return {"book": book, "status": "ok", "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"book": None, "status": classify_book_error(exc), "error": str(exc)}


def _parse_level(row: Any) -> tuple[float, float]:
    if isinstance(row, dict):
        return float(row.get("price") or 0), float(row.get("size") or 0)
    return float(row[0]), float(row[1])


def parse_ask_ladder(book: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not book:
        return []
    asks = book.get("asks") or []
    levels = [_parse_level(r) for r in asks]
    return sorted((p, s) for p, s in levels if p > 0 and s > 0)


def parse_bid_ladder(book: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not book:
        return []
    bids = book.get("bids") or []
    levels = [_parse_level(r) for r in bids]
    return sorted(((p, s) for p, s in levels if p > 0 and s > 0), reverse=True)


def walk_ask_ladder(
    book: dict[str, Any] | None,
    *,
    target_shares: float,
    max_levels: int = 10,
) -> dict[str, Any]:
    ladder_src = parse_ask_ladder(book)[:max_levels]
    filled = 0.0
    cost = 0.0
    ladder: list[dict[str, Any]] = []
    for price, size in ladder_src:
        take = min(size, target_shares - filled)
        if take <= 0:
            break
        filled += take
        cost += take * price
        ladder.append(
            {
                "price": round(price, 6),
                "size": round(size, 4),
                "take": round(take, 4),
                "cum_size": round(filled, 4),
            }
        )
        if filled >= target_shares:
            break
    vwap = cost / filled if filled > 0 else 0.0
    return {
        "vwap": round(vwap, 6),
        "filled_shares": round(filled, 4),
        "levels_used": len(ladder),
        "ladder": ladder,
    }


def walk_bid_ladder(
    book: dict[str, Any] | None,
    *,
    target_shares: float,
    max_levels: int = 10,
) -> dict[str, Any]:
    ladder_src = parse_bid_ladder(book)[:max_levels]
    filled = 0.0
    proceeds = 0.0
    ladder: list[dict[str, Any]] = []
    for price, size in ladder_src:
        take = min(size, target_shares - filled)
        if take <= 0:
            break
        filled += take
        proceeds += take * price
        ladder.append(
            {
                "price": round(price, 6),
                "size": round(size, 4),
                "take": round(take, 4),
                "cum_size": round(filled, 4),
            }
        )
        if filled >= target_shares:
            break
    vwap = proceeds / filled if filled > 0 else 0.0
    return {
        "vwap": round(vwap, 6),
        "filled_shares": round(filled, 4),
        "levels_used": len(ladder),
        "ladder": ladder,
    }


def best_ask(book: dict[str, Any] | None) -> tuple[float, float]:
    ladder = parse_ask_ladder(book)
    if not ladder:
        return 0.0, 0.0
    return ladder[0]


def best_bid(book: dict[str, Any] | None) -> tuple[float, float]:
    ladder = parse_bid_ladder(book)
    if not ladder:
        return 0.0, 0.0
    return ladder[0]


def walk_binary_ask_depth(
    yes_book: dict[str, Any] | None,
    no_book: dict[str, Any] | None,
    *,
    target_shares: float,
    max_levels: int = 10,
) -> dict[str, Any]:
    yes = walk_ask_ladder(yes_book, target_shares=target_shares, max_levels=max_levels)
    no = walk_ask_ladder(no_book, target_shares=target_shares, max_levels=max_levels)
    fillable = min(yes["filled_shares"], no["filled_shares"])
    return {
        "vwap_yes": yes["vwap"],
        "vwap_no": no["vwap"],
        "fillable_shares": round(fillable, 4),
        "depth_levels": max(yes["levels_used"], no["levels_used"]),
        "yes_ladder": yes["ladder"],
        "no_ladder": no["ladder"],
    }


def walk_binary_bid_depth(
    yes_book: dict[str, Any] | None,
    no_book: dict[str, Any] | None,
    *,
    target_shares: float,
    max_levels: int = 10,
) -> dict[str, Any]:
    yes = walk_bid_ladder(yes_book, target_shares=target_shares, max_levels=max_levels)
    no = walk_bid_ladder(no_book, target_shares=target_shares, max_levels=max_levels)
    fillable = min(yes["filled_shares"], no["filled_shares"])
    return {
        "vwap_bid_yes": yes["vwap"],
        "vwap_bid_no": no["vwap"],
        "fillable_shares": round(fillable, 4),
        "depth_levels": max(yes["levels_used"], no["levels_used"]),
        "yes_ladder": yes["ladder"],
        "no_ladder": no["ladder"],
    }


def walk_multi_ask_depth(
    books: list[dict[str, Any] | None],
    *,
    target_shares: float,
    max_levels: int = 10,
) -> dict[str, Any]:
    walks = [
        walk_ask_ladder(b, target_shares=target_shares, max_levels=max_levels) for b in books
    ]
    fillable = min(w["filled_shares"] for w in walks) if walks else 0.0
    return {
        "vwaps": [w["vwap"] for w in walks],
        "fillable_shares": round(fillable, 4),
        "depth_levels": max((w["levels_used"] for w in walks), default=0),
        "ladders": [w["ladder"] for w in walks],
    }
