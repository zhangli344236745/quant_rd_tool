from __future__ import annotations

from datetime import UTC, datetime, timedelta

from quant_rd_tool.crypto_options_compare import build_aligned_expiry_compare


def test_aligned_expiry_strike_ladder_mocked(monkeypatch):
    now = datetime.now(UTC)
    exp_b = (now + timedelta(days=28)).strftime("%y%m%d")
    exp_d = (now + timedelta(days=28)).strftime("%d%b%y").upper()
    date_key = (now + timedelta(days=28)).date().isoformat()

    def fake_marks(*_a, **_k):
        return [
            {"symbol": f"BTC-{exp_b}-{k}-C", "markIV": "0.55"}
            for k in (95000, 100000, 105000)
        ]

    def fake_b_index(*_a, **_k):
        return 100_000.0

    def fake_d_summary(*_a, **_k):
        return [
            {"instrument_name": f"BTC-{exp_d}-{k}-C", "mark_iv": 52.0}
            for k in (95000, 100000, 105000)
        ]

    def fake_d_index(*_a, **_k):
        return 100_010.0

    monkeypatch.setattr("quant_rd_tool.crypto_options_compare.fetch_mark_rows", fake_marks)
    monkeypatch.setattr("quant_rd_tool.crypto_options_compare.binance_index", fake_b_index)
    monkeypatch.setattr("quant_rd_tool.crypto_options_compare.fetch_book_summary", fake_d_summary)
    monkeypatch.setattr("quant_rd_tool.crypto_options_compare.deribit_index", fake_d_index)

    out = build_aligned_expiry_compare("BTC", expiry_date=date_key, n=1)
    assert out["available"]
    assert out["expiry_date"] == date_key
    assert len(out["rows"]) == 3
    atm = out["atm"]
    assert atm["iv_spread_pp"] == 3.0
    assert out["comparison"]["aligned_expiry"] is True
