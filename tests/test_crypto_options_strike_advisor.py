from __future__ import annotations

from quant_rd_tool.crypto_options_strike_advisor import (
    advise_call_purchase,
    advise_put_purchase,
    enrich_strike_report_with_advice,
    summarize_purchase_advice,
)


def _row(strike: float, moneyness: float, model: float, impl: float) -> dict:
    edge = round(model - impl, 4)
    model_put = round(1 - model + 0.05, 4)
    impl_put = round(1 - impl + 0.03, 4)
    return {
        "strike": strike,
        "moneyness_pct": moneyness,
        "mark_iv": 0.5,
        "model": {
            "expiry_itm_call": model,
            "touch_call": model + 0.1,
            "expiry_itm_put": model_put,
        },
        "implied": {"expiry_itm_call": impl, "expiry_itm_put": impl_put},
        "edge_expiry": edge,
        "edge_expiry_put": round(model_put - impl_put, 4),
        "symbol": f"BTC-250627-{int(strike)}-C",
    }


def test_bearish_spot_avoids_buy():
    out = advise_call_purchase(
        _row(100_000, 0, 0.5, 0.48),
        spot=100_000,
        spot_stance="看跌",
    )
    assert out["verdict"] == "不建议买入"


def test_bullish_atm_positive_edge_can_consider():
    out = advise_call_purchase(
        _row(100_000, 0.5, 0.52, 0.45),
        spot=100_000,
        spot_stance="看涨",
        iv_alert_level="normal",
    )
    assert out["verdict"] == "可考虑买入"


def test_hot_iv_deep_otm_avoid():
    out = advise_call_purchase(
        _row(110_000, 10, 0.2, 0.25),
        spot=100_000,
        spot_stance="看涨",
        iv_alert_level="hot",
        iv_percentile=95,
    )
    assert out["verdict"] in ("观望", "不建议买入")


def test_bullish_spot_avoids_put_buy():
    out = advise_put_purchase(
        _row(95_000, -5, 0.5, 0.48),
        spot=100_000,
        spot_stance="看涨",
    )
    assert out["verdict"] == "不建议买入"
    assert out["side"] == "put"


def test_bearish_atm_put_can_consider():
    out = advise_put_purchase(
        _row(100_000, 0, 0.5, 0.48),
        spot=100_000,
        spot_stance="看跌",
        iv_alert_level="normal",
    )
    assert out["verdict"] in ("可考虑买入", "观望")


def test_enrich_strike_report():
    report = {
        "spot": 100_000,
        "rows": [
            _row(100_000, 0, 0.55, 0.45),
            _row(105_000, 5, 0.3, 0.32),
        ],
    }
    enrich_strike_report_with_advice(
        report,
        spot_stance="看涨",
        iv_alert_level="normal",
    )
    assert report["purchase_summary"]["headline"]
    assert all(r.get("purchase") for r in report["rows"])
    assert all(r.get("purchase_put") for r in report["rows"])


def test_summarize_picks_best_strike():
    rows = [
        {**_row(100_000, 0, 0.55, 0.45), "purchase": {"verdict": "可考虑买入"}},
        {**_row(105_000, 5, 0.3, 0.32), "purchase": {"verdict": "观望"}},
    ]
    s = summarize_purchase_advice(rows, spot_stance="看涨", iv_alert_level="normal")
    assert s["best_strike"] == 100_000
    assert s["consider_count"] == 1
