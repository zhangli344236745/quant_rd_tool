from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from quant_rd_tool.crypto_options_greeks import build_greeks_chain, normalize_greeks


def test_normalize_greeks_flat_and_nested():
    flat = normalize_greeks({"delta": "0.55", "gamma": "0.0001", "theta": "-10", "vega": "100"})
    assert flat["delta"] == 0.55
    nested = normalize_greeks({"greeks": {"delta": 0.4, "vega": 80.0}})
    assert nested["vega"] == 80.0


def test_build_greeks_chain_aligned(monkeypatch):
    now = datetime.now(UTC)
    exp_b = (now + timedelta(days=28)).strftime("%y%m%d")
    exp_d = (now + timedelta(days=28)).strftime("%d%b%y").upper()
    date_key = (now + timedelta(days=28)).date().isoformat()
    strike = 100_000.0

    marks = [
        {
            "symbol": f"BTC-{exp_b}-{int(strike)}-C",
            "markIV": "0.55",
            "delta": "0.52",
            "gamma": "0.00011",
            "theta": "-120",
            "vega": "900",
        },
        {
            "symbol": f"BTC-{exp_b}-{int(strike)}-P",
            "markIV": "0.58",
            "delta": "-0.48",
            "gamma": "0.00010",
            "theta": "-100",
            "vega": "850",
        },
    ]
    deribit = [
        {
            "instrument_name": f"BTC-{exp_d}-{int(strike)}-C",
            "mark_iv": 54.0,
            "greeks": {"delta": 0.51, "gamma": 0.00012, "theta": -115, "vega": 880},
        },
        {
            "instrument_name": f"BTC-{exp_d}-{int(strike)}-P",
            "mark_iv": 57.0,
            "greeks": {"delta": -0.49, "gamma": 0.00009, "theta": -95, "vega": 820},
        },
    ]

    def fake_b_grouped(*_a, **_k):
        exp = datetime.strptime(exp_b, "%y%m%d").replace(tzinfo=UTC)
        return (
            {exp: [{"strike": strike, "mark_iv": 0.55, "side": "C", "symbol": marks[0]["symbol"]}]},
            {exp: [{"strike": strike, "iv": 0.54, "side": "C", "symbol": deribit[0]["instrument_name"]}]},
            100_000.0,
            99_900.0,
        )

    with (
        patch("quant_rd_tool.crypto_options_greeks.fetch_mark_rows", return_value=marks),
        patch("quant_rd_tool.crypto_options_greeks.fetch_book_summary", return_value=deribit),
        patch("quant_rd_tool.crypto_options_greeks._load_venue_expiry_groups", side_effect=fake_b_grouped),
    ):
        out = build_greeks_chain("BTC", n=0)

    assert out["available"]
    assert out["expiry_date"] == date_key
    assert len(out["rows"]) == 1
    call_b = out["rows"][0]["call"]["binance"]
    assert call_b["greeks"]["delta"] == 0.52
    put_d = out["rows"][0]["put"]["deribit"]
    assert put_d["greeks"]["delta"] == -0.49


def test_build_greeks_chain_missing_venue_expiry_graceful(monkeypatch):
    now = datetime.now(UTC)
    exp_b = (now + timedelta(days=28)).replace(hour=8, minute=0, second=0, microsecond=0)
    date_key = exp_b.date().isoformat()

    def fake_load(*_a, **_k):
        return (
            {exp_b: [{"strike": 100_000.0, "mark_iv": 0.55, "side": "C", "symbol": "BTC-x-C"}]},
            {},
            100_000.0,
            None,
        )

    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_greeks._load_venue_expiry_groups",
        fake_load,
    )
    out = build_greeks_chain("BTC", expiry_date=date_key)
    assert not out["available"]
    assert "expiry" in out["reason"].lower() or "common" in out["reason"].lower()
