from __future__ import annotations

from unittest.mock import patch

import pytest

from quant_rd_tool.crypto_news_feeds import (
    DEFAULT_FEEDS,
    fetch_all_feeds,
    fetch_feed_items,
    normalize_entry,
    parse_feed_content,
)

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Fed raises rates by 25 bps</title>
      <link>https://example.com/fed-rates</link>
      <pubDate>Mon, 03 Jun 2026 12:00:00 GMT</pubDate>
      <description>Bitcoin and crypto markets watch closely.</description>
      <guid>https://example.com/fed-rates</guid>
    </item>
    <item>
      <title>Local sports roundup</title>
      <link>https://example.com/sports</link>
      <pubDate>Mon, 03 Jun 2026 11:00:00 GMT</pubDate>
      <description>Scores from yesterday.</description>
    </item>
  </channel>
</rss>
"""


def test_default_feeds_has_mvp_sources():
    ids = {f["id"] for f in DEFAULT_FEEDS}
    assert {"coindesk", "cointelegraph", "fed", "sec"}.issubset(ids)


def test_parse_feed_content_normalizes_items():
    items = parse_feed_content(SAMPLE_RSS, source_id="fed")
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "Fed raises rates by 25 bps"
    assert first["link"] == "https://example.com/fed-rates"
    assert first["source_id"] == "fed"
    assert first["summary"]
    assert first["id"]


def test_normalize_entry_strips_html():
    entry = {
        "title": "<b>BTC</b> surges",
        "link": "https://example.com/btc",
        "summary": "<p>Markets rally</p>",
        "published": "2026-06-03T12:00:00Z",
        "id": "abc",
    }
    out = normalize_entry(entry, source_id="coindesk")
    assert "<" not in out["title"]
    assert "BTC" in out["title"]


def test_fetch_feed_items_uses_http_and_parses():
    feed = {"id": "fed", "name": "Fed", "url": "https://example.com/rss"}

    class FakeResponse:
        content = SAMPLE_RSS.encode()
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    with patch("quant_rd_tool.crypto_news_feeds.httpx.get", return_value=FakeResponse()):
        items = fetch_feed_items(feed, timeout=5)
    assert len(items) == 2
    assert items[0]["source_id"] == "fed"


def test_fetch_all_feeds_continues_on_failure():
    good = {"id": "fed", "name": "Fed", "url": "https://example.com/good"}
    bad = {"id": "bad", "name": "Bad", "url": "https://example.com/bad"}

    def side_effect(url, **kwargs):
        if "bad" in url:
            raise TimeoutError("timeout")
        class FakeResponse:
            content = SAMPLE_RSS.encode()
            def raise_for_status(self) -> None:
                return None
        return FakeResponse()

    with patch("quant_rd_tool.crypto_news_feeds.httpx.get", side_effect=side_effect):
        items, errors = fetch_all_feeds([good, bad])
    assert len(items) >= 2
    assert any(e["feed_id"] == "bad" for e in errors)
