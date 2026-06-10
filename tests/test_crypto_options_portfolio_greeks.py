from __future__ import annotations

from quant_rd_tool.crypto_options_portfolio_greeks import (
    aggregate_portfolio_greeks,
    build_portfolio_greeks_report,
    legs_from_overlay,
    legs_from_strategy,
)


def _fake_chain(spot: float = 100_000.0, atm: float = 100_000.0) -> dict:
    return {
        "available": True,
        "spot": spot,
        "atm_strike": atm,
        "dte": 28,
        "expiry_date": "2026-07-01",
        "contract_index": {
            f"binance:{atm}:C": {
                "greeks": {"delta": 0.52, "gamma": 0.0001, "theta": -120.0, "vega": 900.0},
                "mark_iv": 0.55,
            },
            f"binance:{atm}:P": {
                "greeks": {"delta": -0.48, "gamma": 0.0001, "theta": -100.0, "vega": 850.0},
                "mark_iv": 0.58,
            },
            "binance:105000.0:C": {
                "greeks": {"delta": 0.35, "gamma": 0.00008, "theta": -80.0, "vega": 700.0},
                "mark_iv": 0.52,
            },
            "binance:95000.0:P": {
                "greeks": {"delta": -0.32, "gamma": 0.00008, "theta": -75.0, "vega": 680.0},
                "mark_iv": 0.54,
            },
        },
        "rows": [],
    }


def test_legs_from_strategy_spot_and_short_strangle():
    strat = {
        "name": "卖出宽跨式",
        "legs": [
            {"side": "S", "type": "C", "strike": 105_000.0},
            {"side": "S", "type": "P", "strike": 95_000.0},
        ],
    }
    legs = legs_from_strategy(
        strat,
        chain=_fake_chain(),
        spot_pct=0.7,
        options_pct=0.3,
    )
    assert legs[0]["kind"] == "spot"
    assert legs[0]["contribution"]["delta"] == 0.7
    opt_legs = [lg for lg in legs if lg["kind"] == "option"]
    assert len(opt_legs) == 2
    net_delta = sum(lg["contribution"]["delta"] for lg in legs)
    assert net_delta < 0.7


def test_legs_from_overlay_call_overlay():
    legs = legs_from_overlay(
        "call_overlay",
        chain=_fake_chain(),
        spot_pct=0.8,
        options_pct=0.2,
    )
    assert any(lg["kind"] == "spot" for lg in legs)
    assert any(lg.get("type") == "C" for lg in legs)


def test_aggregate_portfolio_greeks_scenarios():
    legs = [
        {"contribution": {"delta": 0.5, "gamma": 0.0001, "theta": -50.0, "vega": 200.0}},
        {"contribution": {"delta": 0.2, "gamma": 0.0, "theta": -10.0, "vega": 50.0}},
    ]
    summary = aggregate_portfolio_greeks(legs, spot=100_000.0, capital=100_000.0)
    assert summary["net"]["delta"] == 0.7
    assert summary["delta_usd"] == 70_000.0
    assert "scenarios" in summary
    assert summary["risk_level"] in ("低", "中", "高")


def test_build_portfolio_greeks_report_overlay(monkeypatch):
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_portfolio_greeks.build_greeks_chain",
        lambda *_a, **_k: _fake_chain(),
    )
    out = build_portfolio_greeks_report(
        "BTC",
        spot_pct=0.75,
        options_pct=0.25,
        overlay_id="long_straddle",
    )
    assert out["available"]
    assert out["source"]["overlay_id"] == "long_straddle"
    assert len(out["legs"]) >= 2
    assert out["summary"]["net"]["delta"] is not None
