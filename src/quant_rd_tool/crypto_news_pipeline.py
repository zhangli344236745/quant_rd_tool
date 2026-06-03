"""Orchestrate news ingest → score → advise → persist."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from quant_rd_tool.crypto_news_advisor import advise_items
from quant_rd_tool.crypto_news_config import get_crypto_news_config
from quant_rd_tool.crypto_news_feeds import fetch_all_feeds
from quant_rd_tool.crypto_news_search import fetch_web_search, resolve_web_search_provider
from quant_rd_tool.crypto_news_scoring import rank_candidates, score_news_item
from quant_rd_tool.crypto_news_storage import (
    append_item,
    is_seen_url,
    load_digest,
    save_digest,
    url_hash,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


def _market_stance(items: list[dict[str, Any]]) -> str:
    impacts = [
        (item.get("advice") or {}).get("impact") or item.get("impact_direction") or "neutral"
        for item in items
    ]
    if not impacts:
        return "neutral"
    counts = Counter(impacts)
    top, _ = counts.most_common(1)[0]
    if len(counts) > 1 and counts.most_common(2)[1][1] == counts.most_common(2)[0][1]:
        return "mixed"
    return top


def run_news_scan(
    *,
    data_dir: str,
    config: dict[str, Any] | None = None,
    feed_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Full news cycle: fetch feeds, dedupe, score, LLM top N, write digest."""
    cfg = config or get_crypto_news_config()
    if not cfg.get("enabled", True):
        return {"items_processed": 0, "digest": load_digest(data_dir), "skipped": "disabled"}

    feeds = cfg.get("feeds") or []
    if feed_ids:
        allowed = set(feed_ids)
        feeds = [f for f in feeds if f.get("id") in allowed]

    min_score = int(cfg.get("min_score", 40))
    llm_top_n = int(cfg.get("llm_top_n", 5))

    raw_items, fetch_errors = fetch_all_feeds(feeds)
    web_search_cfg = cfg.get("web_search") if isinstance(cfg.get("web_search"), dict) else {}
    search_items: list[dict[str, Any]] = []
    search_errors: list[dict[str, str]] = []
    search_meta: dict[str, Any] = {}
    active_search = resolve_web_search_provider(web_search_cfg)
    if active_search:
        search_items, search_errors, search_meta = fetch_web_search(
            web_search_cfg, data_dir=data_dir
        )
        fetch_errors.extend(search_errors)

    combined_raw = raw_items + search_items
    new_items: list[dict[str, Any]] = []
    for item in combined_raw:
        link = item.get("link")
        if not link:
            continue
        h = url_hash(str(link))
        if is_seen_url(data_dir, h):
            continue
        new_items.append(item)

    scored = [score_news_item(item) for item in new_items]
    candidates = rank_candidates(scored, min_score=min_score, top_n=llm_top_n * 2)
    advised = advise_items(candidates, top_n=llm_top_n)
    top_items = advised[:llm_top_n]

    for item in scored:
        append_item(data_dir, item)

    digest: dict[str, Any] | None = None
    if top_items or scored:
        digest = {
            "generated_at": utc_now_iso(),
            "top_items": top_items,
            "market_stance": _market_stance(top_items),
            "items_scored": len(scored),
            "items_new": len(new_items),
            "fetch_errors": fetch_errors,
            "sources": {
                "rss": len(raw_items),
                "web_search": len(search_items),
                "web_search_provider": active_search,
            },
            "search_usage": search_meta.get("usage"),
        }
        save_digest(data_dir, digest)

    return {
        "items_processed": len(scored),
        "items_new": len(new_items),
        "top_items": len(top_items),
        "fetch_errors": fetch_errors,
        "search_provider": active_search,
        "search_items": len(search_items),
        "search_meta": search_meta,
        "digest": digest,
    }
