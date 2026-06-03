from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from quant_rd_tool.crypto_news_pipeline import run_news_scan
from quant_rd_tool.crypto_news_scheduler import run_news_cycle
from quant_rd_tool.crypto_news_storage import load_digest, news_root, save_digest
from quant_rd_tool.crypto_scheduler import attach_news_digest


SAMPLE_ITEMS = [
    {
        "id": "a1",
        "title": "Fed raises rates",
        "link": "https://example.com/fed",
        "published": "2026-06-03T12:00:00Z",
        "summary": "Federal Reserve hikes amid inflation.",
        "source_id": "fed",
    },
    {
        "id": "a2",
        "title": "BTC ETF sees record inflows",
        "link": "https://example.com/btc-etf",
        "published": "2026-06-03T11:00:00Z",
        "summary": "Bitcoin institutional demand surges.",
        "source_id": "coindesk",
    },
]


def test_run_news_scan_writes_digest(tmp_path: Path):
    config = {
        "enabled": True,
        "min_score": 40,
        "llm_top_n": 2,
        "feeds": [{"id": "fed", "name": "Fed", "url": "https://example.com/rss"}],
    }

    def fake_fetch_all(feeds):
        return SAMPLE_ITEMS, []

    def fake_advise(items, *, top_n):
        return [
            {
                **item,
                "advice": {
                    "headline": item["title"],
                    "impact": "bearish" if "Fed" in item["title"] else "bullish",
                    "confidence": 0.8,
                    "affected_symbols": item.get("symbols") or ["BTC"],
                    "horizon": "days",
                    "advice": "测试建议。仅供参考，不构成投资建议。",
                    "risk_note": "不确定性存在。",
                },
            }
            for item in items
        ]

    with patch("quant_rd_tool.crypto_news_pipeline.fetch_all_feeds", side_effect=fake_fetch_all):
        with patch("quant_rd_tool.crypto_news_pipeline.advise_items", side_effect=fake_advise):
            result = run_news_scan(data_dir=tmp_path, config=config)

    assert result["items_processed"] >= 1
    digest = load_digest(tmp_path)
    assert digest is not None
    assert digest.get("generated_at")
    assert len(digest.get("top_items", [])) >= 1
    assert digest.get("market_stance") in ("bullish", "bearish", "neutral", "mixed")

    digest_path = news_root(tmp_path) / "latest_digest.json"
    assert digest_path.exists()
    on_disk = json.loads(digest_path.read_text(encoding="utf-8"))
    assert on_disk["top_items"]


def test_run_news_cycle_wrapper(tmp_path: Path):
    config = {
        "enabled": True,
        "min_score": 40,
        "llm_top_n": 1,
        "feeds": [],
    }
    expected = {"items_processed": 0, "digest": None}

    with patch("quant_rd_tool.crypto_news_scheduler.get_crypto_news_config", return_value=config):
        with patch("quant_rd_tool.crypto_news_scheduler.run_news_scan", return_value=expected) as mock_scan:
            out = run_news_cycle(data_dir=tmp_path)
    mock_scan.assert_called_once()
    assert out == expected


def test_attach_news_digest_when_fresh(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "data"
    save_digest(
        data_root,
        {
            "generated_at": "2026-06-03T12:00:00+00:00",
            "top_items": [{"title": "Fed raises rates", "score": 80}],
            "market_stance": "bearish",
        },
    )

    from datetime import UTC, datetime

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 3, 12, 30, tzinfo=UTC)

    with patch("quant_rd_tool.crypto_scheduler.datetime", FixedDatetime):
        report = attach_news_digest({}, data_dir=data_root / "crypto")

    assert "news_digest" in report
    assert report["news_digest"]["market_stance"] == "bearish"
    assert len(report["news_digest"]["top_items"]) == 1


def test_attach_news_digest_skips_stale(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "data"
    save_digest(
        data_root,
        {
            "generated_at": "2026-06-03T08:00:00+00:00",
            "top_items": [{"title": "Old news"}],
            "market_stance": "neutral",
        },
    )

    from datetime import UTC, datetime

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 3, 12, 30, tzinfo=UTC)

    with patch("quant_rd_tool.crypto_scheduler.datetime", FixedDatetime):
        report = attach_news_digest({}, data_dir=data_root / "crypto")

    assert "news_digest" not in report
