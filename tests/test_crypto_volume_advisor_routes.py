from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from quant_rd_tool.main import app

client = TestClient(app)

FAKE = {
    "symbol": "BTC",
    "pair": "BTC/USDT",
    "timeframe": "1d",
    "metrics": {"volume_ratio_5d_vs_20d": 1.2},
    "advice": {
        "level": "buy",
        "level_label": "建议参与",
        "stance": "看涨",
        "scheme": "breakout_confirmed",
        "scheme_label": "放量突破确认",
        "headline": "建议参与 · 放量突破确认",
        "advice": "test",
        "reasons": [],
        "actions": [],
        "risks": [],
        "confidence": 0.6,
        "suggested_max_position_pct": 0.35,
        "disclaimer": "test",
    },
    "generated_at": "2026-06-12T00:00:00+08:00",
}


def test_volume_advise_route():
    with patch("quant_rd_tool.crypto_volume_advisor.advise_spot_volume", return_value=FAKE):
        r = client.get("/api/v1/crypto/volume/advise?symbol=BTC&timeframe=1d")
    assert r.status_code == 200, r.text
    assert r.json()["symbol"] == "BTC"
    assert r.json()["advice"]["level"] == "buy"


def test_volume_advise_rejects_symbol():
    r = client.get("/api/v1/crypto/volume/advise?symbol=SOL")
    assert r.status_code == 400
