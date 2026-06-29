from __future__ import annotations

import pandas as pd

from quant_rd_tool.crypto_workflow import synthesize_advice
from quant_rd_tool.crypto_workflow_price_levels import compute_iv_price_guidance


def test_compute_iv_price_guidance_long():
    pg = compute_iv_price_guidance(
        spot=100_000,
        stance="看涨",
        action="buy",
        timeframe="1d",
        atm_iv=0.5,
        dte_days=14,
        sl_sigma=1.0,
        tp_sigma=1.5,
        entry_sigma=0.35,
    )
    assert pg["available"] is True
    assert pg["iv_source"] == "options"
    assert pg["entry_price"] < pg["spot"]
    assert pg["stop_loss_price"] < pg["entry_price"]
    assert pg["take_profit_price"] > pg["entry_price"]


def test_compute_iv_price_guidance_short():
    pg = compute_iv_price_guidance(
        spot=100_000,
        stance="看跌",
        action="sell",
        timeframe="1d",
        atm_iv=0.5,
        horizon_days=7,
    )
    assert pg["side"] == "short"
    assert pg["entry_price"] > pg["spot"]
    assert pg["stop_loss_price"] > pg["entry_price"]
    assert pg["take_profit_price"] < pg["entry_price"]


def test_synthesize_advice_includes_price_guidance():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=100, freq="D"),
            "close": [100_000.0] * 100,
            "symbol": ["CRYPTO_BTC"] * 100,
        }
    )
    ctx = {
        "symbol": "BTC",
        "timeframe": "1d",
        "df": df,
        "steps": {
            "technical": {
                "status": "ok",
                "output": {
                    "stance": "看涨",
                    "score": 3,
                    "analysis": {"risk": {"annualized_volatility": 0.45}},
                },
            },
            "options_vol": {
                "status": "ok",
                "output": {
                    "enabled": True,
                    "scan_item": {"atm_iv": 0.52, "dte": 14, "iv_percentile": 55},
                },
            },
        },
    }
    advice = synthesize_advice(ctx, {})
    pg = advice.get("price_guidance") or {}
    assert pg.get("available")
    assert pg.get("entry_price")
    assert pg.get("stop_loss_price")
    assert pg.get("take_profit_price")
    assert any("IV 价位参考" in b for b in advice.get("bullets") or [])
    segs = advice.get("segments") or {}
    assert segs.get("spot", {}).get("price_guidance", {}).get("available")
