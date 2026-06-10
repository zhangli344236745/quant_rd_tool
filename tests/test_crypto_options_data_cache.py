from __future__ import annotations

import httpx

import quant_rd_tool.crypto_options_data as mod
from quant_rd_tool.crypto_options_data import (
    clear_options_mark_cache,
    fetch_index_price,
    fetch_mark_rows,
)


def test_fetch_mark_rows_uses_cache(monkeypatch):
    clear_options_mark_cache()
    calls = {"n": 0}

    def fake_get(self, url, **kwargs):
        calls["n"] += 1
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=[{"symbol": "BTC-260626-100000-C", "markIV": "0.5"}], request=req)

    monkeypatch.setattr("quant_rd_tool.crypto_options_data.httpx.Client.get", fake_get)

    rows1 = fetch_mark_rows()
    rows2 = fetch_mark_rows()
    assert len(rows1) == 1
    assert rows2 == rows1
    assert calls["n"] == 1


def test_fetch_mark_rows_serves_stale_on_failure(monkeypatch):
    clear_options_mark_cache()
    calls = {"n": 0}

    def fake_get(self, url, **kwargs):
        calls["n"] += 1
        req = httpx.Request("GET", url)
        if calls["n"] == 1:
            return httpx.Response(200, json=[{"symbol": "ETH-260626-3000-C", "markIV": "0.6"}], request=req)
        return httpx.Response(503, request=req)

    monkeypatch.setattr("quant_rd_tool.crypto_options_data.httpx.Client.get", fake_get)
    monkeypatch.setattr("quant_rd_tool.crypto_options_data.time.sleep", lambda *_a: None)

    first = fetch_mark_rows()
    assert mod._MARK_ROWS_CACHE is not None
    mod._MARK_ROWS_CACHE = (mod.time.time() - 100, first)
    second = fetch_mark_rows()
    assert first == second
    assert calls["n"] == 4


def test_fetch_index_price_cached(monkeypatch):
    clear_options_mark_cache()
    calls = {"n": 0}

    def fake_get(self, url, **kwargs):
        calls["n"] += 1
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"indexPrice": "3500.5"}, request=req)

    monkeypatch.setattr("quant_rd_tool.crypto_options_data.httpx.Client.get", fake_get)

    px1 = fetch_index_price("ETH")
    px2 = fetch_index_price("ETH")
    assert px1 == 3500.5
    assert px2 == 3500.5
    assert calls["n"] == 1
