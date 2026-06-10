from __future__ import annotations

from quant_rd_tool.crypto_options_strategies import build_strategy_pack, suggest_strategies


def test_high_iv_neutral_suggests_sell_vol():
    item = {
        "base": "BTC",
        "alert_level": "hot",
        "iv_percentile": 85,
        "iv_change_24h_pct": 12,
        "atm_iv": 0.65,
        "underlying_price": 100_000,
    }
    strategies = suggest_strategies(scan_item=item, spot_stance="中性", spot=100_000)
    assert strategies
    kinds = {s["id"] for s in strategies}
    assert "sell_strangle" in kinds or "sell_straddle" in kinds


def test_bullish_low_iv_suggests_directional():
    item = {
        "base": "ETH",
        "alert_level": "normal",
        "iv_percentile": 25,
        "atm_iv": 0.45,
        "underlying_price": 3000,
    }
    report = {
        "base": "ETH",
        "spot": 3000,
        "rows": [
            {
                "strike": 3100,
                "moneyness_pct": 3.3,
                "edge_expiry": 0.05,
                "symbol": "ETH-260627-3100-C",
            }
        ],
    }
    pack = build_strategy_pack(scan_item=item, strike_report=report, spot_stance="看涨")
    assert pack["strategies"]
    kinds = {s["id"] for s in pack["strategies"]}
    assert "buy_call" in kinds or "bull_call_spread" in kinds
