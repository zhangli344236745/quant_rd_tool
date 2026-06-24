from __future__ import annotations

from fastapi.testclient import TestClient

from quant_rd_tool.main import app

client = TestClient(app)


def test_polymarket_scan_route(monkeypatch):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(
        pa,
        "scan_markets",
        lambda cfg, force=False, http_get=None: {
            "markets_scanned": 2,
            "opportunities_count": 1,
            "best_edge_bps": 40.0,
            "items": [{"condition_id": "c1", "opportunity": True, "edge_bps": 40}],
        },
    )
    monkeypatch.setattr(pa, "load_config", pa.PolymarketArbConfig)

    r = client.get("/api/v1/crypto/polymarket/scan")
    assert r.status_code == 200
    assert r.json()["opportunities_count"] == 1


def test_polymarket_config_put(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)

    r = client.put(
        "/api/v1/crypto/polymarket/config",
        json={"top_n_volume": 30, "min_edge_bps": 25},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["top_n_volume"] == 30
    assert body["min_edge_bps"] == 25


def test_polymarket_open_route(monkeypatch):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "load_config", pa.PolymarketArbConfig)
    monkeypatch.setattr(
        pa,
        "open_paper_position",
        lambda opp, size_shares=None, config=None: {"id": "p1", "status": "open"},
    )

    r = client.post(
        "/api/v1/crypto/polymarket/positions/open",
        json={"condition_id": "c1", "ask_yes": 0.45, "ask_no": 0.5},
    )
    assert r.status_code == 200
    assert r.json()["id"] == "p1"


def test_polymarket_preview_route(monkeypatch):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(
        pa,
        "preview_paper_open_by_condition",
        lambda cid, size_shares=None, config=None: {"net_pnl_usd": 1.5, "size_shares": 10},
    )

    r = client.get("/api/v1/crypto/polymarket/preview", params={"condition_id": "c1"})
    assert r.status_code == 200
    assert r.json()["net_pnl_usd"] == 1.5


def test_polymarket_stats_route(monkeypatch):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(
        pa,
        "build_stats",
        lambda config=None: {"scans_today": 3, "opportunities_today": 1},
    )

    r = client.get("/api/v1/crypto/polymarket/stats")
    assert r.status_code == 200
    assert r.json()["scans_today"] == 3


def test_polymarket_scan_history_route(monkeypatch):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(
        pa,
        "list_scan_history",
        lambda limit=20: [{"markets_scanned": 5, "opportunities_count": 2}],
    )

    r = client.get("/api/v1/crypto/polymarket/scans/history")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


def test_polymarket_scan_latest_empty(monkeypatch):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "load_latest_scan", lambda: None)

    r = client.get("/api/v1/crypto/polymarket/scan/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["markets_scanned"] == 0
    assert body["items"] == []
