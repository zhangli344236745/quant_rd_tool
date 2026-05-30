from quant_rd_tool.perp_state import PerpSymbolState


def test_fail_streak_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    s = PerpSymbolState(symbol="BTC/USDT:USDT", protection_fail_streak=2, daily_date="2026-05-28", daily_start_usdt_total=1000.0)
    s.save(p)
    out = PerpSymbolState.load(p)
    assert out.symbol == "BTC/USDT:USDT"
    assert out.protection_fail_streak == 2
    assert out.daily_date == "2026-05-28"
    assert out.daily_start_usdt_total == 1000.0

