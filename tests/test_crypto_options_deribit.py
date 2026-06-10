from __future__ import annotations

from datetime import UTC, datetime, timedelta

from quant_rd_tool.crypto_options_deribit_data import (
    normalize_mark_iv,
    parse_deribit_instrument,
    pick_atm_contract,
)
from quant_rd_tool.crypto_options_compare import compare_atm_row


def test_parse_deribit_instrument():
    meta = parse_deribit_instrument("BTC-28MAR26-90000-C")
    assert meta
    assert meta["base"] == "BTC"
    assert meta["strike"] == 90000.0
    assert meta["side"] == "C"


def test_normalize_mark_iv_percent_and_decimal():
    assert normalize_mark_iv(52.5) == 0.525
    assert normalize_mark_iv(0.525) == 0.525


def test_pick_atm_deribit():
    now = datetime.now(UTC)
    exp = (now + timedelta(days=28)).strftime("%d%b%y").upper()
    rows = [
        {
            "instrument_name": f"BTC-{exp}-85000-C",
            "mark_iv": 55.0,
        },
        {
            "instrument_name": f"BTC-{exp}-90000-C",
            "mark_iv": 54.0,
        },
    ]
    atm = pick_atm_contract(rows, "BTC", 86_000.0, min_days=7)
    assert atm
    assert atm["strike"] == 85000.0
    assert atm["atm_iv"] == 0.55


def test_compare_atm_row_spread():
    item = compare_atm_row(
        {
            "base": "BTC",
            "atm_iv": 0.58,
            "underlying_price": 100_000,
            "expiry": "2026-06-27T00:00:00+00:00",
            "dte": 28,
            "contract": "BTC-260627-100000-C",
        },
        {
            "base": "BTC",
            "atm_iv": 0.52,
            "underlying_price": 99_900,
            "expiry": "2026-06-27T00:00:00+00:00",
            "dte": 28,
            "contract": "BTC-27JUN26-100000-C",
        },
    )
    assert item["comparison"]["available"]
    assert item["comparison"]["iv_spread_pp"] == 6.0
    assert item["comparison"]["richer_venue"] == "binance"
