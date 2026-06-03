"""Monthly usage tracking and quota for web search APIs (Tavily / SerpAPI)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool.crypto_news_storage import news_root

_PROVIDERS = ("tavily", "serpapi")


def usage_path(data_dir: str | Path) -> Path:
    return news_root(data_dir) / "search_usage.json"


def current_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _empty_provider_stats() -> dict[str, int]:
    return {"queries": 0, "results": 0}


def _empty_month() -> dict[str, dict[str, int]]:
    return {p: _empty_provider_stats() for p in _PROVIDERS}


def load_usage(data_dir: str | Path) -> dict[str, Any]:
    path = usage_path(data_dir)
    if not path.is_file():
        return {"months": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"months": {}}
    if not isinstance(data.get("months"), dict):
        data["months"] = {}
    return data


def save_usage(data_dir: str | Path, data: dict[str, Any]) -> None:
    path = usage_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _month_bucket(data: dict[str, Any], month: str) -> dict[str, dict[str, int]]:
    months = data.setdefault("months", {})
    if month not in months or not isinstance(months.get(month), dict):
        months[month] = _empty_month()
    bucket = months[month]
    for p in _PROVIDERS:
        if p not in bucket or not isinstance(bucket.get(p), dict):
            bucket[p] = _empty_provider_stats()
        bucket[p].setdefault("queries", 0)
        bucket[p].setdefault("results", 0)
    return bucket


def get_provider_usage(
    data_dir: str | Path,
    provider: str,
    *,
    month: str | None = None,
) -> dict[str, int]:
    month = month or current_month()
    data = load_usage(data_dir)
    bucket = _month_bucket(data, month)
    stats = bucket.get(provider) or _empty_provider_stats()
    return {"queries": int(stats.get("queries") or 0), "results": int(stats.get("results") or 0)}


def resolve_monthly_limit(web_search_cfg: dict[str, Any] | None, provider: str) -> int:
    """Monthly query cap; 0 means unlimited."""
    ws = web_search_cfg or {}
    per_key = f"monthly_query_limit_{provider}"
    if per_key in ws and ws[per_key] is not None:
        return max(0, int(ws[per_key]))
    if ws.get("monthly_query_limit") is not None:
        return max(0, int(ws["monthly_query_limit"]))
    return 150


def remaining_queries(
    data_dir: str | Path,
    provider: str,
    web_search_cfg: dict[str, Any] | None,
    *,
    month: str | None = None,
) -> int | None:
    """Queries left this month; None when unlimited."""
    limit = resolve_monthly_limit(web_search_cfg, provider)
    if limit <= 0:
        return None
    used = get_provider_usage(data_dir, provider, month=month)["queries"]
    return max(0, limit - used)


def record_search_usage(
    data_dir: str | Path,
    provider: str,
    *,
    queries: int = 1,
    results: int = 0,
    month: str | None = None,
) -> dict[str, int]:
    month = month or current_month()
    data = load_usage(data_dir)
    bucket = _month_bucket(data, month)
    stats = bucket.setdefault(provider, _empty_provider_stats())
    stats["queries"] = int(stats.get("queries") or 0) + max(0, queries)
    stats["results"] = int(stats.get("results") or 0) + max(0, results)
    save_usage(data_dir, data)
    return {"queries": stats["queries"], "results": stats["results"]}


def usage_summary(
    data_dir: str | Path,
    web_search_cfg: dict[str, Any] | None,
    *,
    provider: str | None = None,
    month: str | None = None,
) -> dict[str, Any]:
    month = month or current_month()
    ws = web_search_cfg or {}
    providers = [provider] if provider else list(_PROVIDERS)
    by_provider: dict[str, Any] = {}
    for p in providers:
        used = get_provider_usage(data_dir, p, month=month)
        limit = resolve_monthly_limit(ws, p)
        remaining = None if limit <= 0 else max(0, limit - used["queries"])
        by_provider[p] = {
            "queries_used": used["queries"],
            "results_fetched": used["results"],
            "monthly_query_limit": limit if limit > 0 else None,
            "queries_remaining": remaining,
            "limit_reached": limit > 0 and used["queries"] >= limit,
        }
    active = provider
    active_stats = by_provider.get(active or "", {}) if active else {}
    return {
        "month": month,
        "providers": by_provider,
        "active_provider": active,
        "queries_used": active_stats.get("queries_used", 0),
        "monthly_query_limit": active_stats.get("monthly_query_limit"),
        "queries_remaining": active_stats.get("queries_remaining"),
        "limit_reached": active_stats.get("limit_reached", False),
    }
