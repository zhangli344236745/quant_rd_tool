from __future__ import annotations

import json
from pathlib import Path

from quant_rd_tool.crypto_options_portfolio_greeks import (
    aggregate_multi_portfolio_greeks,
    build_multi_from_lists,
    estimate_option_margin_usd,
    legs_from_strategy,
)
from quant_rd_tool.crypto_options_portfolio_greeks_history import (
    append_greeks_snapshot,
    load_greeks_history,
    persist_portfolio_greeks_report,
    portfolio_id_from_bases,
    snapshot_from_report,
)


def _fake_chain(spot: float = 100_000.0, atm: float = 100_000.0) -> dict:
    return {
        "available": True,
        "spot": spot,
        "atm_strike": atm,
        "dte": 28,
        "contract_index": {
            f"binance:{atm}:C": {
                "greeks": {"delta": 0.52, "gamma": 0.0001, "theta": -120.0, "vega": 900.0},
                "mark_iv": 0.55,
                "mark_price": 2500.0,
            },
        },
        "rows": [],
    }


def test_estimate_option_margin_long_and_short():
    long_m = estimate_option_margin_usd(
        spot=100_000,
        strike=100_000,
        mark_price_usd=2_500,
        side="B",
        opt_type="C",
    )
    assert long_m == 2_500
    short_m = estimate_option_margin_usd(
        spot=100_000,
        strike=105_000,
        mark_price_usd=1_000,
        side="S",
        opt_type="C",
    )
    assert short_m >= 10_000


def test_legs_margin_mode_uses_contracts(tmp_path):
    strat = {"legs": [{"side": "B", "type": "C", "strike": 100_000.0}]}
    legs = legs_from_strategy(
        strat,
        chain=_fake_chain(),
        spot_pct=0.5,
        options_pct=0.5,
        scale_mode="margin",
        capital=100_000,
        base="BTC",
    )
    spot_leg = next(lg for lg in legs if lg["kind"] == "spot")
    assert spot_leg["contribution"]["delta"] == 0.5
    opt_leg = next(lg for lg in legs if lg["kind"] == "option")
    assert opt_leg.get("margin_usd", 0) > 0
    assert opt_leg["contracts"] != 0


def test_multi_aggregate_and_history(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_portfolio_greeks.build_greeks_chain",
        lambda base, **_k: {**_fake_chain(), "base": base},
    )
    report = build_multi_from_lists(
        ["BTC", "ETH"],
        weights=[1, 1],
        capital=100_000,
        overlay_id="call_overlay",
        data_dir=str(tmp_path),
    )
    assert report["available"]
    assert report["multi"]
    assert portfolio_id_from_bases(["ETH", "BTC"]) == "multi:BTC,ETH"
    assert len(report["constituents"]) == 2
    summary = aggregate_multi_portfolio_greeks(report["constituents"], capital=100_000)
    assert "delta_usd" in summary

    row = snapshot_from_report(report)
    assert row and row["portfolio_id"] == "multi:BTC,ETH"
    path = persist_portfolio_greeks_report(report, data_dir=str(tmp_path))
    assert path and path.is_file()
    items = load_greeks_history("multi:BTC,ETH", data_dir=str(tmp_path))
    assert len(items) == 1
    assert items[0]["delta_usd"] is not None


def test_append_greeks_snapshot_roundtrip(tmp_path):
    row = {
        "ts": "2026-06-10T00:00:00+00:00",
        "portfolio_id": "BTC",
        "delta_usd": 12_345.0,
        "net": {"theta": -50},
    }
    append_greeks_snapshot(row, data_dir=str(tmp_path))
    hist_path = Path(tmp_path) / "options_portfolio_greeks" / "BTC.jsonl"
    assert hist_path.exists()
    loaded = json.loads(hist_path.read_text(encoding="utf-8").strip())
    assert loaded["delta_usd"] == 12_345.0
