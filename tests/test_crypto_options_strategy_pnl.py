from __future__ import annotations

from quant_rd_tool.crypto_options_strategies import build_strategy_pack
from quant_rd_tool.crypto_options_strategy_pnl import attach_strategy_pnl


def _strike_report_with_prices():
    return {
        "base": "BTC",
        "spot": 100_000.0,
        "dte": 28,
        "rows": [
            {
                "strike": 100_000.0,
                "symbol": "BTC-260626-100000-C",
                "mark_price": "2500",
            },
            {
                "strike": 105_000.0,
                "symbol": "BTC-260626-105000-C",
                "mark_price": "1200",
            },
            {
                "strike": 95_000.0,
                "symbol": "BTC-260626-95000-P",
                "mark_price": "1100",
            },
        ],
    }


def test_bull_call_spread_pnl():
    strategy = {
        "id": "bull_call_spread",
        "name": "牛市看涨价差",
        "base": "BTC",
        "legs": [
            {"side": "B", "type": "C", "strike": 100_000.0},
            {"side": "S", "type": "C", "strike": 105_000.0},
        ],
    }
    out = attach_strategy_pnl(
        [strategy],
        spot=100_000.0,
        dte=28,
        strike_report=_strike_report_with_prices(),
    )[0]
    pc = out["pnl"]["per_contract"]
    assert pc["available"]
    assert pc["is_debit"]
    assert pc["max_loss_usd"] > 0
    assert pc["max_profit_usd"] > 0
    assert out["pnl"]["stop_loss"]["primary_rule"]
    assert out["pnl"]["scaled"]["available"]


def test_short_strangle_unlimited_loss_flag():
    strategy = {
        "id": "sell_strangle",
        "name": "卖出宽跨式",
        "base": "BTC",
        "legs": [
            {"side": "S", "type": "C", "strike": 105_000.0},
            {"side": "S", "type": "P", "strike": 95_000.0},
        ],
    }
    out = attach_strategy_pnl(
        [strategy],
        spot=100_000.0,
        dte=28,
        strike_report=_strike_report_with_prices(),
    )[0]
    pc = out["pnl"]["per_contract"]
    assert pc["available"]
    assert pc["is_debit"] is False
    assert pc["unlimited_loss"] is True
    assert pc["max_profit_usd"] > 0
    assert out["pnl"]["stop_loss"]["premium_stop_usd"] == pc["max_profit_usd"] * 2


def test_build_strategy_pack_includes_pnl():
    item = {
        "base": "BTC",
        "alert_level": "hot",
        "iv_percentile": 85,
        "atm_iv": 0.55,
        "underlying_price": 100_000,
        "dte": 28,
    }
    pack = build_strategy_pack(
        scan_item=item,
        strike_report=_strike_report_with_prices(),
        spot_stance="中性",
    )
    top = pack["strategies"][0]
    assert "pnl" in top
    if top.get("legs"):
        assert top["pnl"]["per_contract"]["available"]
