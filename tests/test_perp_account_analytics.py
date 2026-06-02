from __future__ import annotations


def test_fetch_daily_pnl_aggregates(monkeypatch):
    from quant_rd_tool import perp_account_analytics as paa

    class FakeEx:
        def fapiPrivateGetIncome(self, params):
            it = params.get("incomeType")
            if it == "REALIZED_PNL":
                return [{"time": 1717200000000, "income": "1.5", "incomeType": "REALIZED_PNL"}]
            if it == "FUNDING_FEE":
                return [{"time": 1717200000000, "income": "0.2", "incomeType": "FUNDING_FEE"}]
            if it == "COMMISSION":
                return [{"time": 1717200000000, "income": "-0.1", "incomeType": "COMMISSION"}]
            return []

        def close(self):
            return None

    monkeypatch.setattr(paa, "_exchange", lambda **_k: FakeEx())
    out = paa.fetch_daily_pnl(days=2)
    assert out["enabled"] is True
    assert out["items"]
    row = out["items"][0]
    assert abs(row["net"] - (1.5 + 0.2 - 0.1)) < 1e-6


def test_fetch_balances_missing_keys(monkeypatch):
    from quant_rd_tool import perp_account_analytics as paa

    monkeypatch.setattr(paa.settings, "binance_api_key", None)
    monkeypatch.setattr(paa.settings, "binance_api_secret", None)
    out = paa.fetch_future_balances()
    assert out["enabled"] is False

