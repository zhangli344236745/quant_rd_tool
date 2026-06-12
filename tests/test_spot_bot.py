from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from quant_rd_tool.binance_bot import BinanceBot, BotConfig


def _ohlcv(n: int = 120, trend: float = 0.004) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 * (1 + trend) ** np.arange(n)
    return pd.DataFrame(
        {
            "timestamp": (dates.astype("int64") // 10**6).astype(int),
            "date": dates,
            "symbol": ["CRYPTO_BTC"] * n,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": np.full(n, 1e6),
        }
    )


def test_dry_run_plans_order_with_sl_tp(tmp_path):
    df = _ohlcv()
    with patch("quant_rd_tool.binance_bot.cxt.fetch_ohlcv", return_value=df):
        bot = BinanceBot(
            BotConfig(symbol="BTC", dry_run=True, state_dir=str(tmp_path), telemetry_enabled=False)
        )
        result = bot.run_once()
    assert result["dry_run"] is True
    order = result["order"]
    assert order is not None
    if order["side"] == "buy":
        assert order["sl_price"] is not None
        assert order["tp_price"] is not None
        assert order["sl_price"] < result["price"] < order["tp_price"]


def test_paper_mode_buy_and_track(tmp_path):
    df = _ohlcv()
    with patch("quant_rd_tool.binance_bot.cxt.fetch_ohlcv", return_value=df):
        bot = BinanceBot(
            BotConfig(
                symbol="BTC",
                paper_mode=True,
                paper_initial_cash=10_000.0,
                quote_amount=10_000.0,
                state_dir=str(tmp_path),
                telemetry_enabled=False,
            )
        )
        result = bot.run_once()
    assert result["mode"] == "paper"
    assert "performance" in result
    perf = result["performance"]
    assert perf["initial_cash"] == 10_000.0
    assert "equity" in perf


def test_paper_dedup_same_bar(tmp_path):
    df = _ohlcv()
    with patch("quant_rd_tool.binance_bot.cxt.fetch_ohlcv", return_value=df):
        bot = BinanceBot(
            BotConfig(
                symbol="BTC",
                paper_mode=True,
                quote_amount=10_000.0,
                paper_initial_cash=10_000.0,
                state_dir=str(tmp_path),
                telemetry_enabled=False,
            )
        )
        bot.run_once()
        second = bot.run_once()
    # Same bar_end → second run must not place a new order
    assert "去重" in second["message"]
    assert second["order"] is None


def test_enhanced_signal_gate_blocks_conflict(tmp_path):
    base_up = _ohlcv(trend=0.006)
    htf_down = _ohlcv(trend=-0.006)

    def fake_fetch(symbol, *, timeframe, limit, exchange_id):
        # base timeframe bullish, higher timeframe bearish
        return htf_down if timeframe in ("1d", "1w") else base_up

    cfg = BotConfig(
        symbol="BTC",
        timeframe="4h",
        dry_run=True,
        require_htf_confirm=True,
        state_dir=str(tmp_path),
        telemetry_enabled=False,
    )
    with patch("quant_rd_tool.binance_bot.cxt.fetch_ohlcv", side_effect=fake_fetch):
        bot = BinanceBot(cfg)
        result = bot.run_once()
    sig = result["signal"]
    if sig.get("base_action") == "buy":
        assert sig["action"] == "hold"
        assert sig["gated"] is True


def test_reset_paper(tmp_path):
    df = _ohlcv()
    with patch("quant_rd_tool.binance_bot.cxt.fetch_ohlcv", return_value=df):
        bot = BinanceBot(
            BotConfig(
                symbol="BTC", paper_mode=True, quote_amount=10_000.0,
                state_dir=str(tmp_path), telemetry_enabled=False,
            )
        )
        bot.run_once()
        out = bot.reset_paper()
    assert out["reset"] is True
