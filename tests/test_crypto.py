"""Tests for crypto analyzer and bot (no network)."""

from __future__ import annotations

import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analyzer import (
    analyze_crypto_ohlcv,
    build_crypto_narrative,
    derive_trading_signal,
)


def _fake_ohlcv(n: int = 80, trend: float = 0.002) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 * (1 + trend) ** pd.Series(range(n))
    ts = (dates.astype("int64") // 10**6).astype(int)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "date": dates,
            "symbol": ["CRYPTO_BTC"] * n,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": 1e6,
        }
    )


def test_symbol_helpers():
    assert cxt.to_ccxt_symbol("BTC") == "BTC/USDT"
    assert cxt.to_ccxt_symbol("ETHUSDT") == "ETH/USDT"
    assert cxt.to_qlib_code("ETH") == "CRYPTO_ETH"


def test_bullish_signal():
    df = _fake_ohlcv(80, trend=0.003)
    analysis = analyze_crypto_ohlcv(df)
    signal = derive_trading_signal(analysis)
    assert signal["stance"] in ("看涨", "看跌", "中性")
    assert signal["action"] in ("buy", "sell", "hold")
    narrative = build_crypto_narrative(analysis, signal, timeframe="1d")
    assert narrative["stance"] == signal["stance"]
    assert "investment_brief" in narrative
    assert "投资方向说明" in narrative["investment_brief"]["markdown"]


def test_investment_brief_neutral():
    from quant_rd_tool.crypto_analyzer import build_investment_brief, derive_trading_signal

    df = _fake_ohlcv(120, trend=0.0)
    analysis = analyze_crypto_ohlcv(df)
    signal = derive_trading_signal(analysis)
    brief = build_investment_brief(
        analysis,
        signal,
        pair="BTC/USDT",
        timeframe="5m",
    )
    assert brief["one_liner"]
    assert any(s["title"].startswith("结论") for s in brief["sections"])
    assert "5m" in brief["markdown"] or "K 线" in brief["markdown"]


def test_merge_crypto_signals():
    from quant_rd_tool.crypto_ml import merge_crypto_signals

    tech = {
        "stance": "看涨",
        "action": "buy",
        "score": 2,
        "reasons": ["均线：多头排列"],
    }
    ml = {
        "enabled": True,
        "algorithm": "lgb",
        "latest": {"signal": "模型偏多", "predicted_return": 0.01},
        "test_metrics": {"ic": 0.05},
    }
    combined = merge_crypto_signals(tech, ml)
    assert combined["stance"] == "看涨"
    assert combined["agreement"] == "一致"


def test_binance_bot_dry_run():
    from unittest.mock import patch

    from quant_rd_tool.binance_bot import BinanceBot, BotConfig

    df = _fake_ohlcv()
    with patch("quant_rd_tool.binance_bot.cxt.fetch_ohlcv", return_value=df):
        bot = BinanceBot(BotConfig(symbol="BTC", dry_run=True))
        result = bot.run_once()
    assert result["dry_run"] is True
    assert result["order"] is not None
