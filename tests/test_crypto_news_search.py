from __future__ import annotations

from unittest.mock import MagicMock, patch

from quant_rd_tool.crypto_news_pipeline import run_news_scan
from quant_rd_tool.crypto_news_search import (
    fetch_web_search,
    normalize_search_result,
    resolve_web_search_provider,
    search_providers_status,
    search_serpapi,
    search_tavily,
)


def test_normalize_search_result_tavily_shape():
    item = normalize_search_result(
        {
            "title": "BTC hits new high",
            "url": "https://news.example/btc",
            "content": "Bitcoin rallied on ETF flows.",
            "published_date": "2026-06-03",
        },
        provider="tavily",
        query="bitcoin news",
    )
    assert item["title"] == "BTC hits new high"
    assert item["link"] == "https://news.example/btc"
    assert item["source_id"] == "web_search:tavily"
    assert item["search_query"] == "bitcoin news"


def test_normalize_search_result_serpapi_shape():
    item = normalize_search_result(
        {
            "title": "SEC action",
            "link": "https://news.example/sec",
            "snippet": "Regulator files suit.",
            "date": "1 hour ago",
        },
        provider="serpapi",
        query="sec crypto",
    )
    assert item["source_id"] == "web_search:serpapi"
    assert "SEC" in item["title"]


def test_resolve_provider_auto_prefers_tavily(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tv-test")
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    cfg = {"enabled": True, "provider": "auto"}
    assert resolve_web_search_provider(cfg) == "tavily"


def test_resolve_provider_auto_falls_back_serpapi(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("SERPAPI_API_KEY", "serp-test")
    cfg = {"enabled": True, "provider": "auto"}
    assert resolve_web_search_provider(cfg) == "serpapi"


def test_resolve_provider_disabled():
    assert resolve_web_search_provider({"enabled": False, "provider": "auto"}) is None


def test_search_tavily_parses_results():
    def fake_post(url, json):
        assert url.endswith("/search")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"title": "A", "url": "https://a.com", "content": "body a"},
                {"title": "B", "url": "https://b.com", "content": "body b"},
            ]
        }
        return mock_resp

    mock_client = MagicMock()
    mock_client.post = fake_post
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("quant_rd_tool.crypto_news_search.httpx.Client", return_value=mock_client):
        items = search_tavily("btc news", api_key="key", max_results=5)
    assert len(items) == 2
    assert items[0]["source_id"] == "web_search:tavily"


def test_search_serpapi_parses_news_results():
    def fake_get(url, params):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "news_results": [
                {"title": "Headline", "link": "https://x.com/n", "snippet": "text"},
            ]
        }
        return mock_resp

    mock_client = MagicMock()
    mock_client.get = fake_get
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("quant_rd_tool.crypto_news_search.httpx.Client", return_value=mock_client):
        items = search_serpapi("eth news", api_key="key", max_results=3)
    assert len(items) == 1
    assert items[0]["source_id"] == "web_search:serpapi"


def test_fetch_web_search_skips_when_disabled():
    items, errors, meta = fetch_web_search({"enabled": False})
    assert items == []
    assert errors == []
    assert meta["queries_run"] == 0


def test_fetch_web_search_enabled_without_key_returns_empty(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    with patch("quant_rd_tool.crypto_news_search.settings") as mock_settings:
        mock_settings.tavily_api_key = None
        mock_settings.serpapi_api_key = None
        items, errors, meta = fetch_web_search({"enabled": True, "provider": "auto"})
    assert items == []
    assert errors == []


def test_fetch_web_search_runs_queries(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tv-key")
    calls: list[str] = []

    def fake_tavily(query, *, api_key, max_results, timeout):
        calls.append(query)
        return [
            {
                "title": query,
                "link": f"https://x/{len(calls)}",
                "summary": "s",
                "source_id": "web_search:tavily",
            }
        ]

    with patch("quant_rd_tool.crypto_news_search.search_tavily", side_effect=fake_tavily):
        items, errors, meta = fetch_web_search(
            {
                "enabled": True,
                "provider": "tavily",
                "queries": ["q1", "q2"],
                "max_queries_per_cycle": 2,
            }
        )
    assert len(calls) == 2
    assert len(items) == 2
    assert errors == []
    assert meta["queries_run"] == 2


def test_run_news_scan_merges_web_search(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tv-key")
    config = {
        "enabled": True,
        "min_score": 20,
        "llm_top_n": 3,
        "feeds": [],
        "web_search": {
            "enabled": True,
            "provider": "tavily",
            "queries": ["bitcoin regulation"],
            "max_queries_per_cycle": 1,
        },
    }
    search_item = {
        "id": "ws1",
        "title": "SEC sues exchange over compliance",
        "link": "https://example.com/sec-sue",
        "published": "2026-06-03",
        "summary": "SEC enforcement action against crypto exchange.",
        "source_id": "web_search:tavily",
        "search_query": "bitcoin regulation",
    }

    with patch("quant_rd_tool.crypto_news_pipeline.fetch_all_feeds", return_value=([], [])):
        with patch(
            "quant_rd_tool.crypto_news_pipeline.fetch_web_search",
            return_value=([search_item], [], {"queries_run": 1, "usage": None}),
        ):
            with patch(
                "quant_rd_tool.crypto_news_pipeline.advise_items",
                side_effect=lambda items, *, top_n: [
                    {**i, "advice": {"impact": "bearish"}} for i in items[:top_n]
                ],
            ):
                result = run_news_scan(data_dir=tmp_path, config=config)

    assert result["search_items"] == 1
    assert result["search_provider"] == "tavily"
    assert result["items_processed"] >= 1
    digest = result["digest"]
    assert digest is not None
    assert digest["sources"]["web_search"] == 1


def test_search_providers_status(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "x")
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    status = search_providers_status({"enabled": True, "provider": "auto"})
    assert status["tavily_configured"] is True
    assert status["active_provider"] == "tavily"
