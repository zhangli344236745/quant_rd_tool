from __future__ import annotations

from fastapi.testclient import TestClient

from quant_rd_tool.main import app


def test_ws_hft_strategies_route():
    with TestClient(app) as client:
        r = client.get("/api/v1/crypto/ws-hft/strategies")
    assert r.status_code == 200
    assert {s["id"] for s in r.json()} == {"classic_mm", "grid_mm", "vol_mm", "imbalance_mm", "as_mm"}


def test_ws_hft_register_bot(tmp_path, monkeypatch):
    from quant_rd_tool import crypto_ws_hft_storage as st

    monkeypatch.setattr(st, "WS_HFT_DIR", tmp_path)
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "BOTS_INDEX_PATH", tmp_path / "bots.json")

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/crypto/ws-hft/bots",
            json={
                "bot_id": "btc-ws",
                "symbol": "BTC",
                "market_type": "future",
                "strategy_id": "classic_mm",
                "dry_run": True,
                "trigger_mode": "throttle",
            },
        )
    assert r.status_code == 200
    assert r.json()["bot_id"] == "btc-ws"
    assert r.json()["dry_run"] is True


def test_ws_hft_start_requires_confirm_live_when_not_dry_run(tmp_path, monkeypatch):
    from quant_rd_tool import crypto_ws_hft_storage as st

    monkeypatch.setattr(st, "WS_HFT_DIR", tmp_path)
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "BOTS_INDEX_PATH", tmp_path / "bots.json")
    (tmp_path / "bots").mkdir(parents=True)
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "events").mkdir(parents=True)

    with TestClient(app) as client:
        client.post(
            "/api/v1/crypto/ws-hft/bots",
            json={"bot_id": "btc-ws", "dry_run": False, "testnet": True},
        )
        r = client.post("/api/v1/crypto/ws-hft/bots/btc-ws/start", json={})
    assert r.status_code == 400
    assert "confirm_live" in r.json()["detail"]


def test_ws_hft_start_dry_run_ok(tmp_path, monkeypatch):
    from quant_rd_tool import crypto_ws_hft_runner as runner
    from quant_rd_tool import crypto_ws_hft_storage as st

    monkeypatch.setattr(st, "WS_HFT_DIR", tmp_path)
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "BOTS_INDEX_PATH", tmp_path / "bots.json")
    (tmp_path / "bots").mkdir(parents=True)
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "events").mkdir(parents=True)

    async def _noop_loop(self, bot_id: str) -> None:
        return None

    monkeypatch.setattr(runner, "_MANAGER", None)
    monkeypatch.setattr(runner.WsHftRunnerManager, "_run_loop", _noop_loop)

    with TestClient(app) as client:
        client.post(
            "/api/v1/crypto/ws-hft/bots",
            json={"bot_id": "btc-ws", "dry_run": True, "testnet": True},
        )
        r = client.post("/api/v1/crypto/ws-hft/bots/btc-ws/start", json={})
    assert r.status_code == 200
