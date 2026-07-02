from __future__ import annotations

import pandas as pd
import pytest

from quant_rd_tool.crypto_workflow import synthesize_advice
from quant_rd_tool.crypto_workflow_price_levels import (
    compute_iv_price_guidance,
    compute_options_price_guidance,
    compute_perp_price_guidance,
)


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
    assert segs.get("spot", {}).get("price_guidance", {}).get("market_type") == "spot"


def test_compute_perp_price_guidance_long():
    pg = compute_perp_price_guidance(
        spot=100_000,
        perp_mark=100_050,
        stance="看涨",
        action="buy",
        timeframe="1d",
        atm_iv=0.5,
        dte_days=14,
    )
    assert pg["available"] is True
    assert pg["market_type"] == "perp"
    assert pg["perp_mark"] == pytest.approx(100_050)
    assert pg["entry_price"] < pg["perp_mark"]


def test_compute_options_price_guidance_call():
    pg = compute_options_price_guidance(
        spot=100_000,
        opt_stance="偏多",
        spot_stance="看涨",
        timeframe="1d",
        atm_iv=0.55,
        atm_strike=100_000,
        dte_days=14,
    )
    assert pg["available"] is True
    assert pg["market_type"] == "options"
    assert pg["option_type"] == "call"
    assert pg["entry_strike"] == pytest.approx(100_000)
    assert pg["premium_budget_usd"] > 0
    assert pg["take_profit_spot"] > pg["spot"]


def test_synthesize_advice_segment_price_guidance():
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
                "output": {"stance": "看涨", "score": 3, "analysis": {"risk": {"annualized_volatility": 0.45}}},
            },
            "zipline_strategy": {
                "status": "ok",
                "output": {"strategy_id": "ma_cross", "target_pct": 0.4},
            },
            "options_vol": {
                "status": "ok",
                "output": {
                    "enabled": True,
                    "scan_item": {"atm_iv": 0.52, "dte": 14, "iv_percentile": 55, "strike": 100_000},
                    "cross_view": {"summary": "IV 中性", "options_stance": "偏多", "alignment": "共振"},
                    "options_vol": {"advice": {"stance": "偏多", "summary": "可小仓位买 Call"}},
                },
            },
        },
    }
    advice = synthesize_advice(ctx, {})
    by_market = advice.get("price_guidance_by_market") or {}
    assert by_market.get("spot", {}).get("available")
    assert by_market.get("perp", {}).get("available")
    assert by_market.get("options", {}).get("available")
    assert by_market["options"]["option_type"] == "call"
