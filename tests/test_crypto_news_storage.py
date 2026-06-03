from __future__ import annotations

import json
from pathlib import Path

from quant_rd_tool.crypto_news_storage import (
    append_item,
    is_seen_url,
    load_digest,
    load_items,
    mark_seen_url,
    news_root,
    save_digest,
    url_hash,
)


def test_news_root_under_data_dir(tmp_path: Path):
    root = news_root(tmp_path)
    assert root == tmp_path / "crypto" / "news"


def test_append_item_and_load_items(tmp_path: Path):
    item = {"id": "1", "title": "Test", "link": "https://example.com/a", "score": 50}
    append_item(tmp_path, item)
    items = load_items(tmp_path, limit=10)
    assert len(items) == 1
    assert items[0]["title"] == "Test"


def test_save_and_load_digest(tmp_path: Path):
    digest = {
        "generated_at": "2026-06-03T12:00:00+00:00",
        "top_items": [{"title": "Headline"}],
        "market_stance": "neutral",
    }
    save_digest(tmp_path, digest)
    loaded = load_digest(tmp_path)
    assert loaded is not None
    assert loaded["market_stance"] == "neutral"
    assert len(loaded["top_items"]) == 1


def test_dedupe_by_url_hash(tmp_path: Path):
    link = "https://example.com/story"
    h = url_hash(link)
    assert not is_seen_url(tmp_path, h)
    mark_seen_url(tmp_path, h)
    assert is_seen_url(tmp_path, h)
    state_path = news_root(tmp_path) / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert h in state["seen_url_hashes"]
