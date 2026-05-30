from quant_rd_tool.perp_state import PerpSymbolState


def test_soft_fields_roundtrip(tmp_path):
    p = tmp_path / "soft.json"
    s = PerpSymbolState(
        symbol="ETH/USDT:USDT",
        soft_protection_active=True,
        soft_sl_price=2900.0,
        soft_tp_price=3100.0,
        soft_position_side="long",
    )
    s.save(p)
    out = PerpSymbolState.load(p)
    assert out.soft_protection_active is True
    assert out.soft_sl_price == 2900.0
    assert out.soft_tp_price == 3100.0
    assert out.soft_position_side == "long"
