import pandas as pd

from quant_rd_tool.perp_risk import compute_notional, compute_notional_atr, resolve_open_notional


def test_notional_atr_scales_with_stop_distance():
    # Wider stop (larger ATR) -> smaller position for same risk budget
    n_tight = compute_notional_atr(
        free_usdt=1000,
        risk_fraction=0.02,
        confidence=1.0,
        ref_price=100.0,
        atr=1.0,
        sl_atr=1.5,
    )
    n_wide = compute_notional_atr(
        free_usdt=1000,
        risk_fraction=0.02,
        confidence=1.0,
        ref_price=100.0,
        atr=3.0,
        sl_atr=1.5,
    )
    assert n_tight > n_wide
    # risk 20 USDT, stop 1.5 -> amount = 20/1.5, notional = amount * 100
    assert abs(n_tight - (20 / 1.5) * 100) < 1e-6


def test_hybrid_caps_atr_with_leverage_fraction():
    out = resolve_open_notional(
        mode="hybrid",
        free_usdt=1000,
        risk_fraction=0.2,
        confidence=0.5,
        ref_price=100.0,
        leverage=3,
        atr=1.0,
        sl_atr=1.5,
    )
    cap = compute_notional(
        free_usdt=1000,
        total_risk_fraction=0.2,
        confidence=0.5,
        leverage=3,
    )
    assert out["leverage_cap_usdt"] == cap
    assert out["notional_usdt"] <= cap
    assert out["atr_notional_usdt"] is not None


def test_hybrid_fallback_when_no_atr():
    out = resolve_open_notional(
        mode="hybrid",
        free_usdt=500,
        risk_fraction=0.1,
        confidence=1.0,
        ref_price=50.0,
        leverage=2,
        atr=None,
    )
    assert out["notional_usdt"] == out["leverage_cap_usdt"]


def test_portfolio_cap_applied():
    out = resolve_open_notional(
        mode="leverage_fraction",
        free_usdt=1000,
        risk_fraction=0.5,
        confidence=1.0,
        ref_price=100.0,
        leverage=5,
        portfolio_cap_usdt=200.0,
    )
    assert out["notional_usdt"] == 200.0


def test_atr_mode_zero_without_atr():
    out = resolve_open_notional(
        mode="atr",
        free_usdt=1000,
        risk_fraction=0.1,
        confidence=1.0,
        ref_price=100.0,
        leverage=1,
        atr=None,
    )
    assert out["notional_usdt"] == 0.0
