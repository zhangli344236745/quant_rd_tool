"""Optional web search ingestion for crypto/macro news (Tavily / SerpAPI)."""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx

from quant_rd_tool.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_QUERIES: tuple[str, ...] = (
    "Bitcoin Ethereum crypto market news today",
    "Federal Reserve interest rates cryptocurrency impact",
    "SEC crypto regulation enforcement",
)

TAVILY_URL = "https://api.tavily.com/search"
SERPAPI_URL = "https://serpapi.com/search.json"


def _tavily_key() -> str | None:
    return settings.tavily_api_key or os.environ.get("TAVILY_API_KEY") or None


def _serpapi_key() -> str | None:
    return settings.serpapi_api_key or os.environ.get("SERPAPI_API_KEY") or None


def normalize_search_result(raw: dict[str, Any], *, provider: str, query: str) -> dict[str, Any]:
    link = str(raw.get("url") or raw.get("link") or "").strip()
    title = str(raw.get("title") or "").strip()
    summary = str(
        raw.get("content") or raw.get("snippet") or raw.get("description") or ""
    ).strip()
    published = str(raw.get("published_date") or raw.get("date") or "")
    if not title or not link:
        return {}
    return {
        "id": hashlib.sha256(link.encode()).hexdigest()[:16],
        "title": title,
        "link": link,
        "published": published,
        "summary": summary[:2000],
        "source_id": f"web_search:{provider}",
        "search_query": query,
    }


def resolve_web_search_provider(web_search_cfg: dict[str, Any] | None) -> str | None:
    """Pick active provider when web search is enabled; None if disabled or no keys."""
    ws = web_search_cfg or {}
    if not ws.get("enabled", False):
        return None
    provider = str(ws.get("provider") or "auto").lower()
    has_tavily = bool(_tavily_key())
    has_serp = bool(_serpapi_key())
    if provider == "none":
        return None
    if provider == "tavily":
        return "tavily" if has_tavily else None
    if provider == "serpapi":
        return "serpapi" if has_serp else None
    if has_tavily:
        return "tavily"
    if has_serp:
        return "serpapi"
    return None


def search_providers_status(web_search_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    ws = web_search_cfg or {}
    return {
        "tavily_configured": bool(_tavily_key()),
        "serpapi_configured": bool(_serpapi_key()),
        "enabled": bool(ws.get("enabled", False)),
        "active_provider": resolve_web_search_provider(ws),
    }


def _search_queries(web_search_cfg: dict[str, Any]) -> list[str]:
    raw = web_search_cfg.get("queries")
    if isinstance(raw, list) and raw:
        queries = [str(q).strip() for q in raw if str(q).strip()]
    else:
        queries = list(DEFAULT_SEARCH_QUERIES)
    max_q = int(web_search_cfg.get("max_queries_per_cycle", 3))
    return queries[: max(1, min(max_q, 10))]


def search_tavily(
    query: str,
    *,
    api_key: str,
    max_results: int = 5,
    timeout: float = 20,
) -> list[dict[str, Any]]:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max(1, min(max_results, 10)),
        "search_depth": "basic",
        "include_answer": False,
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(TAVILY_URL, json=payload)
        response.raise_for_status()
        data = response.json()
    items: list[dict[str, Any]] = []
    for row in data.get("results") or []:
        if not isinstance(row, dict):
            continue
        normalized = normalize_search_result(row, provider="tavily", query=query)
        if normalized:
            items.append(normalized)
    return items


def search_serpapi(
    query: str,
    *,
    api_key: str,
    max_results: int = 5,
    timeout: float = 20,
) -> list[dict[str, Any]]:
    params = {
        "engine": "google_news",
        "q": query,
        "api_key": api_key,
        "num": max(1, min(max_results, 10)),
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.get(SERPAPI_URL, params=params)
        response.raise_for_status()
        data = response.json()
    items: list[dict[str, Any]] = []
    for row in data.get("news_results") or data.get("organic_results") or []:
        if not isinstance(row, dict):
            continue
        normalized = normalize_search_result(row, provider="serpapi", query=query)
        if normalized:
            items.append(normalized)
    return items


def fetch_web_search(
    web_search_cfg: dict[str, Any] | None,
    *,
    data_dir: str | Path | None = None,
    timeout: float = 20,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    """Run configured web searches; failures are per-query, never abort the cycle."""
    meta: dict[str, Any] = {
        "queries_run": 0,
        "queries_skipped": 0,
        "results_fetched": 0,
        "usage": None,
    }
    ws = dict(web_search_cfg or {})
    provider = resolve_web_search_provider(ws)
    if not provider:
        if ws.get("enabled"):
            logger.warning(
                "Web search enabled but no provider/key available (set TAVILY_API_KEY or SERPAPI_API_KEY)"
            )
        return [], [], meta

    api_key = _tavily_key() if provider == "tavily" else _serpapi_key()
    if not api_key:
        return [], [{"provider": provider, "error": "API key missing"}], meta

    max_results = int(ws.get("max_results_per_query", 5))
    queries = _search_queries(ws)

    if data_dir is not None:
        from quant_rd_tool.crypto_news_search_usage import (
            record_search_usage,
            remaining_queries,
            usage_summary,
        )

        remaining = remaining_queries(data_dir, provider, ws)
        if remaining is not None and remaining <= 0:
            logger.warning("Web search monthly limit reached for %s", provider)
            meta["usage"] = usage_summary(data_dir, ws, provider=provider)
            meta["limit_reached"] = True
            return [], [
                {
                    "provider": provider,
                    "error": "monthly_query_limit_reached",
                    "month": meta["usage"].get("month"),
                }
            ], meta
        if remaining is not None and len(queries) > remaining:
            meta["queries_skipped"] = len(queries) - remaining
            queries = queries[:remaining]
            logger.info(
                "Trimming web search queries to %d (monthly remaining for %s)",
                len(queries),
                provider,
            )

    all_items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    search_fn = search_tavily if provider == "tavily" else search_serpapi
    usage_mod = None
    if data_dir is not None:
        from quant_rd_tool.crypto_news_search_usage import record_search_usage, usage_summary

        usage_mod = record_search_usage

    for query in queries:
        try:
            batch = search_fn(query, api_key=api_key, max_results=max_results, timeout=timeout)
            all_items.extend(batch)
            meta["queries_run"] += 1
            meta["results_fetched"] += len(batch)
            if usage_mod is not None:
                usage_mod(data_dir, provider, queries=1, results=len(batch))
        except Exception as exc:
            logger.warning("Web search %s query %r failed: %s", provider, query, exc)
            errors.append({"provider": provider, "query": query, "error": str(exc)})

    if data_dir is not None:
        from quant_rd_tool.crypto_news_search_usage import usage_summary

        meta["usage"] = usage_summary(data_dir, ws, provider=provider)

    return all_items, errors, meta
