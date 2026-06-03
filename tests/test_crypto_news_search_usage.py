from __future__ import annotations

from unittest.mock import patch

from quant_rd_tool.crypto_news_search import fetch_web_search
from quant_rd_tool.crypto_news_search_usage import (
    current_month,
    get_provider_usage,
    record_search_usage,
    remaining_queries,
    resolve_monthly_limit,
    usage_summary,
)


def test_record_and_read_usage(tmp_path):
    record_search_usage(tmp_path, "tavily", queries=2, results=8)
    stats = get_provider_usage(tmp_path, "tavily")
    assert stats["queries"] == 2
    assert stats["results"] == 8


def test_remaining_queries_respects_limit(tmp_path):
    ws = {"monthly_query_limit": 10}
    record_search_usage(tmp_path, "tavily", queries=7)
    assert remaining_queries(tmp_path, "tavily", ws) == 3


def test_unlimited_when_limit_zero(tmp_path):
    ws = {"monthly_query_limit": 0}
    record_search_usage(tmp_path, "tavily", queries=100)
    assert remaining_queries(tmp_path, "tavily", ws) is None


def test_usage_summary_structure(tmp_path):
    ws = {"monthly_query_limit": 20}
    record_search_usage(tmp_path, "tavily", queries=5, results=12)
    summary = usage_summary(tmp_path, ws, provider="tavily")
    assert summary["month"] == current_month()
    assert summary["queries_used"] == 5
    assert summary["monthly_query_limit"] == 20
    assert summary["queries_remaining"] == 15
    assert summary["providers"]["tavily"]["results_fetched"] == 12


def test_fetch_web_search_stops_at_monthly_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tv-key")
    ws = {
        "enabled": True,
        "provider": "tavily",
        "queries": ["q1", "q2", "q3"],
        "max_queries_per_cycle": 3,
        "monthly_query_limit": 1,
    }
    record_search_usage(tmp_path, "tavily", queries=1)

    items, errors, meta = fetch_web_search(ws, data_dir=tmp_path)
    assert items == []
    assert errors[0]["error"] == "monthly_query_limit_reached"
    assert meta["limit_reached"] is True


def test_fetch_web_search_trims_queries_to_remaining(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tv-key")
    ws = {
        "enabled": True,
        "provider": "tavily",
        "queries": ["q1", "q2", "q3"],
        "max_queries_per_cycle": 3,
        "monthly_query_limit": 5,
    }
    record_search_usage(tmp_path, "tavily", queries=4)
    calls: list[str] = []

    def fake_tavily(query, *, api_key, max_results, timeout):
        calls.append(query)
        return [{"title": query, "url": f"https://x/{query}", "content": "body"}]

    with patch("quant_rd_tool.crypto_news_search.search_tavily", side_effect=fake_tavily):
        items, errors, meta = fetch_web_search(ws, data_dir=tmp_path)

    assert len(calls) == 1
    assert meta["queries_skipped"] == 2
    assert len(items) == 1
    assert get_provider_usage(tmp_path, "tavily")["queries"] == 5


def test_per_provider_limit_override():
    ws = {"monthly_query_limit": 100, "monthly_query_limit_serpapi": 50}
    assert resolve_monthly_limit(ws, "tavily") == 100
    assert resolve_monthly_limit(ws, "serpapi") == 50
