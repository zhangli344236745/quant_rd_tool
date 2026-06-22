from __future__ import annotations

from fastapi.testclient import TestClient

from quant_rd_tool.main import app

client = TestClient(app)


def test_carry_scan_route(monkeypatch):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(
        cca,
        "scan_watchlist",
        lambda cfg: [{"symbol": "BTC", "composite_apr": 0.2, "entry_alert": True}],
    )
    monkeypatch.setattr(cca, "list_positions", lambda **kw: [])
    monkeypatch.setattr(cca, "load_config", cca.CarryConfig)
    monkeypatch.setattr(
        cca,
        "build_carry_summary",
        lambda cfg, scan_items=None: {"open_count": 0, "entry_alert_count": 1},
    )

    r = client.get("/api/v1/crypto/carry/scan")
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["symbol"] == "BTC"
    assert body["summary"]["entry_alert_count"] == 1


def test_carry_open_route(monkeypatch):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "load_config", cca.CarryConfig)
    monkeypatch.setattr(
        cca,
        "open_paper_carry",
        lambda symbol, notional, config=None, **kwargs: {
            "id": "p1",
            "symbol": symbol,
            "status": "open",
            "notional_usdt": notional,
        },
    )

    r = client.post("/api/v1/crypto/carry/positions/open", json={"symbol": "BTC", "notional_usdt": 5000})
    assert r.status_code == 200
    assert r.json()["id"] == "p1"


def test_carry_config_put(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)

    r = client.put(
        "/api/v1/crypto/carry/config",
        json={"watchlist": ["BTC", "ETH"], "entry_threshold_apr": 0.12},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["watchlist"] == ["BTC", "ETH"]
    assert body["entry_threshold_apr"] == 0.12


def test_carry_preview_route(monkeypatch):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(
        cca,
        "preview_paper_carry",
        lambda symbol, notional, config=None: {
            "symbol": symbol,
            "notional_usdt": notional,
            "profit_estimate": {"funding_daily_usdt": 3.0},
            "risk_warnings": [],
        },
    )

    r = client.get("/api/v1/crypto/carry/preview", params={"symbol": "BTC", "notional_usdt": 10000})
    assert r.status_code == 200
    assert r.json()["symbol"] == "BTC"


def test_carry_close_preview_route(monkeypatch):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(
        cca,
        "preview_close_paper_carry",
        lambda position_id, config=None: {
            "position_id": position_id,
            "symbol": "BTC",
            "pnl_estimate": {"realized_pnl": 12.5},
            "risk_warnings": [],
        },
    )

    r = client.get("/api/v1/crypto/carry/positions/p1/close-preview")
    assert r.status_code == 200
    assert r.json()["pnl_estimate"]["realized_pnl"] == 12.5
