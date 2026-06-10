from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from quant_rd_tool.crypto_options_strike_probs import (
    build_strike_ladder,
    prob_expiry_itm_call,
    prob_expiry_itm_put,
    prob_implied_expiry_itm_call,
    prob_implied_expiry_itm_put,
    prob_touch_call_up,
    prob_touch_put_down,
)


def test_prob_expiry_atm_near_half_with_zero_drift():
    p = prob_expiry_itm_call(100.0, 100.0, mu_ann=0.0, sigma_ann=0.4, dte_days=30)
    assert p is not None
    assert 0.35 < p < 0.65


def test_prob_touch_at_least_expiry_for_otm():
    spot, strike = 100.0, 110.0
    dte = 30.0
    mu, sig = 0.05, 0.5
    pe = prob_expiry_itm_call(spot, strike, mu_ann=mu, sigma_ann=sig, dte_days=dte)
    pt = prob_touch_call_up(spot, strike, mu_ann=mu, sigma_ann=sig, dte_days=dte)
    assert pe is not None and pt is not None
    assert pt >= pe - 1e-6


def test_prob_touch_one_when_strike_below_spot():
    p = prob_touch_call_up(100.0, 90.0, mu_ann=0.0, sigma_ann=0.5, dte_days=30)
    assert p == 1.0


def test_implied_matches_bs_d2():
    spot, strike, iv, dte = 100.0, 100.0, 0.5, 365.0
    p = prob_implied_expiry_itm_call(spot, strike, iv=iv, dte_days=dte)
    assert p is not None
    assert 0.4 < p < 0.6


def test_put_probs_complement_call_at_atm():
    spot, strike, dte = 100.0, 100.0, 30.0
    mu, sig = 0.0, 0.5
    pc = prob_expiry_itm_call(spot, strike, mu_ann=mu, sigma_ann=sig, dte_days=dte)
    pp = prob_expiry_itm_put(spot, strike, mu_ann=mu, sigma_ann=sig, dte_days=dte)
    assert pc is not None and pp is not None
    assert abs(pc + pp - 1.0) < 0.05


def test_put_touch_when_strike_above_spot():
    p = prob_touch_put_down(100.0, 110.0, mu_ann=0.0, sigma_ann=0.5, dte_days=30)
    assert p == 1.0


def test_implied_put_complements_call():
    spot, strike, iv, dte = 100.0, 100.0, 0.5, 180.0
    c = prob_implied_expiry_itm_call(spot, strike, iv=iv, dte_days=dte)
    p = prob_implied_expiry_itm_put(spot, strike, iv=iv, dte_days=dte)
    assert c is not None and p is not None
    assert abs(c + p - 1.0) < 1e-6


def test_build_strike_ladder_atm_n():
    now = datetime.now(UTC)
    exp = (now + timedelta(days=28)).strftime("%y%m%d")
    marks = []
    for k in range(80, 121, 5):
        marks.append({"symbol": f"BTC-{exp}-{k * 1000}-C", "markIV": "0.55"})
    ladder, warnings = build_strike_ladder(marks, "BTC", 100_000.0, 2)
    assert len(ladder) == 5
    assert not any("only" in w for w in warnings) or len(ladder) >= 3
    strikes = [r["strike"] for r in ladder]
    assert strikes == sorted(strikes)


def test_build_strike_probability_report_mocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base_ts = datetime.now(UTC)
    exp = (base_ts + timedelta(days=30)).strftime("%y%m%d")

    def fake_marks(*_a, **_k):
        return [
            {"symbol": f"BTC-{exp}-{k}-C", "markIV": "0.60"}
            for k in (90000, 95000, 100000, 105000, 110000)
        ]

    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_strike_probs.fetch_mark_rows",
        fake_marks,
    )
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_strike_probs.fetch_index_price",
        lambda *_a, **_k: 100_000.0,
    )
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_strike_probs._load_spot_frame",
        lambda *_a, **_k: None,
    )

    from quant_rd_tool.crypto_options_strike_probs import build_strike_probability_report

    report = build_strike_probability_report("BTC", n=2, data_dir="data/crypto")
    assert report["base"] == "BTC"
    assert len(report["rows"]) == 5
    assert report["rows"][0]["implied"]["expiry_itm_call"] is not None
    assert report["model"]["enabled"] is False
