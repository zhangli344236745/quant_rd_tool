from unittest.mock import patch

import pandas as pd

from quant_rd_tool.binance_perp_bot import BinancePerpBot, PerpBotConfig


def test_resolve_open_sizing_hybrid_uses_atr(tmp_path):
    cfg = PerpBotConfig(
        base="BTC",
        sizing_mode="hybrid",
        usdt_risk_fraction=0.1,
        leverage=2,
        sl_atr=1.5,
        atr_period=2,
    )
    bot = BinancePerpBot(cfg)
    df = pd.DataFrame(
        {
            "high": [102.0, 104.0, 103.0],
            "low": [98.0, 100.0, 99.0],
            "close": [100.0, 101.0, 102.0],
        }
    )

    with patch.object(bot, "_fetch_atr", return_value=2.0):
        out = bot._resolve_open_sizing(
            signal={"confidence": 1.0},
            free_usdt=1000,
            ref_price=100.0,
            ex=None,
        )

    assert out["mode"] == "hybrid"
    assert out["atr"] == 2.0
    assert out["atr_notional_usdt"] is not None
    assert out["notional_usdt"] <= out["leverage_cap_usdt"]
    assert out["notional_usdt"] > 0
