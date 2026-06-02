from __future__ import annotations


def test_get_position_falls_back_to_position_risk(monkeypatch):
    from quant_rd_tool import perp_order_manager as pom

    class FakeEx:
        def fetch_positions(self, *_a, **_k):
            raise RuntimeError("no fetch_positions")

        def market(self, symbol: str):
            assert symbol == "ETH/USDT:USDT"
            return {"id": "ETHUSDT"}

        def fapiPrivateGetPositionRisk(self, params):
            assert params["symbol"] == "ETHUSDT"
            return [
                {
                    "symbol": "ETHUSDT",
                    "positionAmt": "0.151",
                    "entryPrice": "1981.69",
                    "unRealizedProfit": "1.32",
                }
            ]

        def close(self):
            return None

    monkeypatch.setattr(pom, "_exchange", lambda **_k: FakeEx())
    monkeypatch.setattr(pom.settings, "binance_api_key", "x")
    monkeypatch.setattr(pom.settings, "binance_api_secret", "y")

    out = pom.get_position(base="ETH", testnet=False)
    assert out["enabled"] is True
    assert out["position"]["side"] == "long"
    assert out["position"]["contracts"] == 0.151

