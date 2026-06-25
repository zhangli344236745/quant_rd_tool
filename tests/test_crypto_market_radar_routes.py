from fastapi.testclient import TestClient

from quant_rd_tool.main import app

client = TestClient(app)


def test_market_radar_scan_latest_empty():
    r = client.get("/api/v1/crypto/market-radar/scan/latest")
    assert r.status_code == 200
    data = r.json()
    assert data["binance_new"] == []


def test_market_radar_config_get_put(tmp_path, monkeypatch):
    radar = tmp_path / "market_radar"
    monkeypatch.setattr("quant_rd_tool.crypto_market_radar.RADAR_DIR", radar)

    r = client.get("/api/v1/crypto/market-radar/config")
    assert r.status_code == 200
    assert r.json()["top_n_liquidity"] == 200

    r2 = client.put(
        "/api/v1/crypto/market-radar/config",
        json={"min_24h_change_pct": 15.0},
    )
    assert r2.status_code == 200
    assert r2.json()["min_24h_change_pct"] == 15.0


def test_market_radar_builtin_status():
    r = client.get("/api/v1/crypto/market-radar/builtin/status")
    assert r.status_code == 200
    assert "running" in r.json()
