from quant_rd_tool.trading_state import TradingState


def test_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    s = TradingState(last_seen_bar_end="2026-01-01 00:10:00", last_action="long")
    s.save(p)
    out = TradingState.load(p)
    assert out.last_seen_bar_end == "2026-01-01 00:10:00"
    assert out.last_action == "long"

