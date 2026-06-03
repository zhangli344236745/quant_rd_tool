"""RSS feed fetch and normalization for crypto/macro news."""

from __future__ import annotations

import hashlib
import logging
import re
from html import unescape
from typing import Any

import feedparser
import httpx

logger = logging.getLogger(__name__)

DEFAULT_FEEDS: list[dict[str, str]] = [
    {
        "id": "coindesk",
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    },
    {
        "id": "cointelegraph",
        "name": "Cointelegraph",
        "url": "https://cointelegraph.com/rss",
    },
    {
        "id": "fed",
        "name": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
    },
    {
        "id": "sec",
        "name": "SEC Press",
        "url": "https://www.sec.gov/news/pressreleases.rss",
    },
]

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    if not text:
        return ""
    cleaned = _TAG_RE.sub(" ", unescape(text))
    return " ".join(cleaned.split())


def _entry_id(entry: dict[str, Any], link: str) -> str:
    for key in ("id", "guid"):
        val = entry.get(key)
        if val:
            return str(val)
    return hashlib.sha256(link.encode()).hexdigest()[:16]


def normalize_entry(entry: dict[str, Any], *, source_id: str) -> dict[str, Any]:
    link = str(entry.get("link") or entry.get("id") or "").strip()
    title = _strip_html(str(entry.get("title") or ""))
    summary_raw = entry.get("summary") or entry.get("description") or ""
    summary = _strip_html(str(summary_raw))
    published = entry.get("published") or entry.get("updated") or ""
    return {
        "id": _entry_id(entry, link),
        "title": title,
        "link": link,
        "published": str(published),
        "summary": summary,
        "source_id": source_id,
    }


def parse_feed_content(content: str | bytes, *, source_id: str) -> list[dict[str, Any]]:
    parsed = feedparser.parse(content)
    items: list[dict[str, Any]] = []
    for entry in parsed.entries:
        normalized = normalize_entry(dict(entry), source_id=source_id)
        if normalized["title"] and normalized["link"]:
            items.append(normalized)
    return items


def fetch_feed_items(feed: dict[str, str], *, timeout: float = 15) -> list[dict[str, Any]]:
    url = feed["url"]
    source_id = feed.get("id") or feed.get("name") or "unknown"
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return parse_feed_content(response.content, source_id=source_id)


def fetch_all_feeds(
    feeds: list[dict[str, str]],
    *,
    timeout: float = 15,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Fetch all feeds; return (items, errors). Individual failures do not abort."""
    all_items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for feed in feeds:
        feed_id = feed.get("id") or feed.get("url") or "unknown"
        try:
            items = fetch_feed_items(feed, timeout=timeout)
            all_items.extend(items)
        except Exception as exc:
            logger.warning("Feed %s failed: %s", feed_id, exc)
            errors.append({"feed_id": feed_id, "error": str(exc)})
    return all_items, errors
