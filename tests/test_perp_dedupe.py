from quant_rd_tool.trading_state import TradingState
from quant_rd_tool.binance_perp_bot import _should_trade_bar


def test_dedupe_same_bar_skips():
    st = TradingState(last_seen_bar_end="2026-01-01 00:10:00", last_action="long")
    assert _should_trade_bar(st, bar_end="2026-01-01 00:10:00") is False
    assert _should_trade_bar(st, bar_end="2026-01-01 00:20:00") is True

