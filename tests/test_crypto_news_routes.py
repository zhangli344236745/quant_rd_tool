from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_crypto_news_routes_smoke(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.main import app

    client = TestClient(app)

    r = client.get("/api/v1/crypto/news/config")
    assert r.status_code == 200, r.text
    assert "min_score" in r.json()

    r = client.post("/api/v1/crypto/news/config", json={"min_score": 45, "llm_top_n": 3})
    assert r.status_code == 200, r.text
    assert r.json()["min_score"] == 45

    r = client.get("/api/v1/crypto/news/digest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("empty") is True
    assert body.get("top_items") == []

    r = client.get("/api/v1/crypto/news/items?limit=10")
    assert r.status_code == 200
    assert r.json()["count"] == 0

    fake = {"items_processed": 0, "items_new": 0, "top_items": 0, "digest": None}
    with patch("quant_rd_tool.crypto_news_scheduler.run_news_cycle", return_value=fake):
        r = client.post("/api/v1/crypto/news/scan", json={"data_dir": str(tmp_path)})
    assert r.status_code == 200, r.text
    assert r.json()["items_processed"] == 0
