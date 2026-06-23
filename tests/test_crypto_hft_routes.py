from __future__ import annotations

from fastapi.testclient import TestClient

from quant_rd_tool.main import app


def test_hft_strategies_route():
    with TestClient(app) as client:
        r = client.get("/api/v1/crypto/hft/strategies")
    assert r.status_code == 200
    assert {s["id"] for s in r.json()} == {"classic_mm", "grid_mm", "vol_mm", "imbalance_mm", "as_mm"}


def test_hft_register_bot(tmp_path, monkeypatch):
    from quant_rd_tool import crypto_hft_storage as st

    monkeypatch.setattr(st, "HFT_DIR", tmp_path)
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "BOTS_INDEX_PATH", tmp_path / "bots.json")

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/crypto/hft/bots",
            json={
                "bot_id": "btc-mm",
                "symbol": "BTC",
                "market_type": "future",
                "strategy_id": "classic_mm",
                "testnet": True,
            },
        )
    assert r.status_code == 200
    assert r.json()["bot_id"] == "btc-mm"


def test_hft_cycle_mock(tmp_path, monkeypatch):
    from quant_rd_tool import crypto_hft_storage as st

    monkeypatch.setattr(st, "HFT_DIR", tmp_path)
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "BOTS_INDEX_PATH", tmp_path / "bots.json")
    (tmp_path / "bots").mkdir(parents=True)
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "events").mkdir(parents=True)

    with TestClient(app) as client:
        client.post(
            "/api/v1/crypto/hft/bots",
            json={"bot_id": "btc-mm", "symbol": "BTC", "strategy_id": "classic_mm"},
        )

    from quant_rd_tool import crypto_hft as eng

    class _FakeEx:
        def fetch_order_book(self, symbol, limit=5):
            return {"bids": [[100, 1]], "asks": [[100.1, 1]]}

        def fetch_open_orders(self, symbol):
            return []

        def fetch_positions(self, symbols):
            return [{"symbol": symbols[0], "contracts": 0, "side": "long"}]

        def fetch_ticker(self, symbol):
            return {"last": 100}

        def create_order(self, *a, **kw):
            return {"id": "o1"}

    monkeypatch.setattr(eng, "is_kill_switch_active", lambda: False)
    monkeypatch.setattr(eng, "default_exchange_factory", lambda cfg: _FakeEx())

    with TestClient(app) as client:
        r = client.post("/api/v1/crypto/hft/bots/btc-mm/cycle")
    assert r.status_code == 200
    assert r.json()["placed"] >= 0
