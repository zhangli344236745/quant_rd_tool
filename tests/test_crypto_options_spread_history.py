from __future__ import annotations

from pathlib import Path

from quant_rd_tool.crypto_options_spread_history import (
    append_spread_snapshot,
    load_spread_history,
    persist_aligned_spread,
    snapshot_from_aligned,
)


def test_snapshot_from_aligned_builds_row():
    aligned = {
        "available": True,
        "base": "BTC",
        "expiry_date": "2026-06-27",
        "dte": 17.5,
        "atm_strike": 100_000,
        "atm": {"binance_iv": 0.55, "deribit_iv": 0.52},
        "comparison": {
            "iv_spread_pp": 3.0,
            "richer_venue": "Binance",
            "alert_level": "elevated",
        },
    }
    row = snapshot_from_aligned(aligned)
    assert row is not None
    assert row["base"] == "BTC"
    assert row["iv_spread_pp"] == 3.0
    assert row["binance_iv"] == 0.55


def test_persist_and_load_roundtrip(tmp_path: Path):
    aligned = {
        "available": True,
        "base": "ETH",
        "expiry_date": "2026-07-04",
        "dte": 24.0,
        "atm_strike": 3500,
        "atm": {"binance_iv": 0.6, "deribit_iv": 0.58},
        "comparison": {
            "iv_spread_pp": 2.0,
            "richer_venue": "Binance",
            "alert_level": "normal",
        },
    }
    persist_aligned_spread(aligned, data_dir=tmp_path)
    items = load_spread_history("ETH", data_dir=tmp_path)
    assert len(items) == 1
    assert items[0]["iv_spread_pp"] == 2.0

    append_spread_snapshot(
        {**items[0], "iv_spread_pp": 4.5, "base": "ETH"},
        data_dir=tmp_path,
    )
    items2 = load_spread_history("ETH", data_dir=tmp_path, limit=10)
    assert len(items2) == 2
    assert items2[-1]["iv_spread_pp"] == 4.5


def test_load_empty_when_missing(tmp_path: Path):
    assert load_spread_history("SOL", data_dir=tmp_path) == []
