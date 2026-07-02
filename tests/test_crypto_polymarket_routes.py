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
        json={
            "top_n_volume": 30,
            "min_edge_bps": 25,
            "crypto_universe_enabled": True,
            "stream_mode": "hybrid",
            "stream_debounce_s": 3,
            "stream_poll_interval_s": 8,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["top_n_volume"] == 30
    assert body["min_edge_bps"] == 25
    assert body["crypto_universe_enabled"] is True
    assert body["stream_mode"] == "hybrid"
    assert body["stream_debounce_s"] == 3
    assert body["stream_poll_interval_s"] == 8


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


def test_polymarket_leaderboard_route(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)

    r = client.get("/api/v1/crypto/polymarket/analytics/leaderboard", params={"limit": 5})
    assert r.status_code == 200
    assert "items" in r.json()


def test_polymarket_advisor_route(monkeypatch):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(
        pa,
        "load_latest_scan",
        lambda: {
            "scanned_at": "2026-06-25T12:00:00+08:00",
            "items": [
                {
                    "condition_id": "c1",
                    "question": "Q?",
                    "strategy_type": "binary_ask",
                    "opportunity": True,
                    "paper_tradable": True,
                    "fillable_shares": 100,
                    "slippage_bps": 0,
                    "depth_levels": 2,
                    "edge_at_size_bps": 200,
                    "edge_at_size": 0.02,
                    "vwap_yes": 0.45,
                    "vwap_no": 0.50,
                    "profit_at_size_usd": 2.0,
                }
            ],
        },
    )

    r = client.get("/api/v1/crypto/polymarket/advisor/recommendations", params={"min_win_rate": 0.5})
    assert r.status_code == 200
    body = r.json()
    assert body["total_opportunities"] >= 1
    assert len(body["top_picks"]) >= 1
    assert "advice" in body["top_picks"][0]


def test_polymarket_edge_trend_route(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)

    r = client.get(
        "/api/v1/crypto/polymarket/analytics/edge-trend",
        params={"condition_id": "c1", "hours": 24},
    )
    assert r.status_code == 200
    assert r.json()["condition_id"] == "c1"


def test_polymarket_backtest_routes(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    (tmp_path / "positions").mkdir()

    for path in (
        "/api/v1/crypto/polymarket/analytics/backtest",
        "/api/v1/crypto/polymarket/analytics/roi-distribution",
        "/api/v1/crypto/polymarket/analytics/advisor-calibration",
        "/api/v1/crypto/polymarket/analytics/strategy-compare",
    ):
        r = client.get(path)
        assert r.status_code == 200, r.text


def test_polymarket_cross_venue_route(monkeypatch):
    from quant_rd_tool import crypto_polymarket_cross_venue as cv

    monkeypatch.setattr(
        cv,
        "build_cross_venue_report",
        lambda base, **k: {
            "base": base.upper(),
            "polymarket_enabled": True,
            "pairs": [],
            "kalshi_count": 0,
        },
    )

    r = client.get("/api/v1/crypto/polymarket/cross-venue", params={"base": "BTC"})
    assert r.status_code == 200
    assert r.json()["base"] == "BTC"


def test_polymarket_cross_venue_all_route(monkeypatch):
    from quant_rd_tool import crypto_polymarket_cross_venue as cv

    monkeypatch.setattr(
        cv,
        "build_cross_venue_report",
        lambda base, **k: {
            "base": base.upper(),
            "pairs": [{"base": base.upper(), "prob_spread_bps": 100}],
        },
    )

    r = client.get("/api/v1/crypto/polymarket/cross-venue/all", params={"bases": "BTC,ETH"})
    assert r.status_code == 200
    body = r.json()
    assert body["pair_count"] == 2
    assert len(body["reports"]) == 2


def test_polymarket_context_route(monkeypatch):
    from quant_rd_tool import crypto_polymarket_context as pmc
    from quant_rd_tool import crypto_polymarket_integration as pmi

    captured: dict[str, str] = {}

    monkeypatch.setattr(
        pmc,
        "fetch_polymarket_context",
        lambda sym, **k: {"enabled": True, "symbol": sym, "markets": [], "top_market": None},
    )

    def _cross(**kwargs):
        captured["stance"] = kwargs.get("spot_stance", "")
        return {"alignment": "共振", "summary": "ok"}

    monkeypatch.setattr(pmi, "synthesize_prediction_cross_view", _cross)

    r = client.get(
        "/api/v1/crypto/polymarket/context",
        params={"symbol": "BTC", "spot_stance": "看涨", "spot_action": "buy"},
    )
    assert r.status_code == 200
    assert r.json()["cross_view"]["alignment"] == "共振"
    assert captured["stance"] == "看涨"


def test_polymarket_cross_venue_history_route(monkeypatch, tmp_path):
    import json
    from datetime import UTC, datetime

    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    hist = tmp_path / "cross_venue_history.jsonl"
    hist.write_text(
        json.dumps({"ts": datetime.now(UTC).isoformat(), "base": "BTC", "prob_spread_bps": 120})
        + "\n",
        encoding="utf-8",
    )

    r = client.get("/api/v1/crypto/polymarket/cross-venue/history", params={"hours": 168})
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_polymarket_stream_status_route():
    r = client.get("/api/v1/crypto/polymarket/stream/status")
    assert r.status_code == 200
    assert "mode" in r.json()
