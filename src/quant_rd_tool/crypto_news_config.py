"""Load crypto_news section from settings.json with env overrides."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool.crypto_news_feeds import DEFAULT_FEEDS
from quant_rd_tool.crypto_news_search import search_providers_status
from quant_rd_tool.network_settings import load_settings

_DEFAULT_WEB_SEARCH: dict[str, Any] = {
    "enabled": False,
    "provider": "auto",
    "max_results_per_query": 5,
    "max_queries_per_cycle": 3,
    "monthly_query_limit": 150,
    "queries": [],
}

_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "min_score": 40,
    "llm_top_n": 5,
    "attach_to_analysis_cycle": True,
    "digest_max_age_minutes": 180,
    "feeds": [],
    "web_search": dict(_DEFAULT_WEB_SEARCH),
}

_SETTINGS_PATH = Path("data/settings.json")


def resolve_news_data_dir(crypto_data_dir: str | Path) -> str:
    """Map scheduler ``data/crypto`` to news storage root ``data``."""
    p = Path(crypto_data_dir)
    if p.name == "crypto":
        return str(p.parent)
    return str(p)


def resolve_news_data_dir_for_api(data_dir: str | Path) -> str:
    """Resolve news storage root; prefer repo-root ``data/`` when cwd differs."""
    from quant_rd_tool.config import _project_root

    base = resolve_news_data_dir(data_dir)
    p = Path(base)
    if p.is_absolute():
        return base
    cwd_path = p
    root_path = _project_root() / base
    for candidate in (cwd_path, root_path):
        if (candidate / "crypto" / "news").is_dir():
            return str(candidate.resolve())
    if root_path.parent == _project_root() and base in ("data", "."):
        return str(root_path)
    return str(cwd_path)


def get_crypto_news_config(settings_path: str | None = None) -> dict[str, Any]:
    raw = load_settings(settings_path)
    section = raw.get("crypto_news") if isinstance(raw.get("crypto_news"), dict) else {}
    cfg = {**_DEFAULT_CONFIG, **section}

    env_top_n = os.environ.get("CRYPTO_NEWS_LLM_TOP_N")
    if env_top_n:
        cfg["llm_top_n"] = int(env_top_n)
    env_min = os.environ.get("CRYPTO_NEWS_MIN_SCORE")
    if env_min:
        cfg["min_score"] = int(env_min)

    ws = cfg.get("web_search") if isinstance(cfg.get("web_search"), dict) else {}
    cfg["web_search"] = {**_DEFAULT_WEB_SEARCH, **ws}
    env_ws = os.environ.get("CRYPTO_NEWS_WEB_SEARCH_ENABLED", "").lower()
    if env_ws in ("1", "true", "yes", "on"):
        cfg["web_search"]["enabled"] = True
    env_limit = os.environ.get("CRYPTO_NEWS_SEARCH_MONTHLY_LIMIT")
    if env_limit is not None and env_limit.strip() != "":
        cfg["web_search"]["monthly_query_limit"] = max(0, int(env_limit))

    feeds = cfg.get("feeds")
    if not feeds:
        cfg["feeds"] = [dict(f) for f in DEFAULT_FEEDS]

    cfg["search_providers"] = search_providers_status(cfg.get("web_search"))
    return cfg


def save_crypto_news_config(
    *,
    settings_path: str | Path | None = None,
    enabled: bool | None = None,
    min_score: int | None = None,
    llm_top_n: int | None = None,
    attach_to_analysis_cycle: bool | None = None,
    digest_max_age_minutes: int | None = None,
    feeds: list[dict[str, Any]] | None = None,
    web_search: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(settings_path) if settings_path else _SETTINGS_PATH
    data = load_settings(path)
    section = dict(data.get("crypto_news") or {}) if isinstance(data.get("crypto_news"), dict) else {}
    if enabled is not None:
        section["enabled"] = enabled
    if min_score is not None:
        section["min_score"] = int(min_score)
    if llm_top_n is not None:
        section["llm_top_n"] = int(llm_top_n)
    if attach_to_analysis_cycle is not None:
        section["attach_to_analysis_cycle"] = attach_to_analysis_cycle
    if digest_max_age_minutes is not None:
        section["digest_max_age_minutes"] = int(digest_max_age_minutes)
    if feeds is not None:
        section["feeds"] = feeds
    if web_search is not None:
        existing_ws = section.get("web_search") if isinstance(section.get("web_search"), dict) else {}
        section["web_search"] = {**_DEFAULT_WEB_SEARCH, **existing_ws, **web_search}
    section["updated_at"] = datetime.now(UTC).isoformat()
    data["crypto_news"] = section
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_crypto_news_config(path)
