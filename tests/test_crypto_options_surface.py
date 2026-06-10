from __future__ import annotations

from datetime import UTC, datetime, timedelta

from quant_rd_tool.crypto_options_surface import (
    build_iv_skew,
    build_term_structure,
    list_expiries,
)


def _fake_marks(base: str = "BTC", spot: float = 100_000.0):
    now = datetime.now(UTC)
    exp1 = (now + timedelta(days=14)).strftime("%y%m%d")
    exp2 = (now + timedelta(days=45)).strftime("%y%m%d")
    marks = []
    for exp, strikes in ((exp1, (95000, 100000, 105000)), (exp2, (90000, 100000, 110000))):
        for k in strikes:
            marks.append({"symbol": f"{base}-{exp}-{k}-C", "markIV": "0.55"})
            marks.append({"symbol": f"{base}-{exp}-{k}-P", "markIV": "0.58"})
    return marks


def test_list_expiries_mocked(monkeypatch):
    marks = _fake_marks()

    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_surface.fetch_mark_rows",
        lambda **_k: marks,
    )
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_surface.fetch_index_price",
        lambda *_a, **_k: 100_000.0,
    )

    out = list_expiries("BTC", min_dte=7)
    assert out["base"] == "BTC"
    assert len(out["expiries"]) >= 2
    assert out["expiries"][0]["atm_iv"] is not None


def test_term_structure_mocked(monkeypatch):
    marks = _fake_marks()
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_surface.fetch_mark_rows",
        lambda **_k: marks,
    )
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_surface.fetch_index_price",
        lambda *_a, **_k: 100_000.0,
    )
    out = build_term_structure("BTC", min_dte=7)
    assert len(out["points"]) >= 2
    dtes = [p["dte"] for p in out["points"]]
    assert dtes == sorted(dtes)


def test_iv_skew_mocked(monkeypatch):
    marks = _fake_marks()
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_surface.fetch_mark_rows",
        lambda **_k: marks,
    )
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_surface.fetch_index_price",
        lambda *_a, **_k: 100_000.0,
    )
    out = build_iv_skew("BTC", min_dte=7)
    assert out["points"]
    strikes = [p["strike"] for p in out["points"]]
    assert strikes == sorted(strikes)
