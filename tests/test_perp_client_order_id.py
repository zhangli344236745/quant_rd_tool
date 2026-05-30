from quant_rd_tool.perp_models import build_client_order_id


def test_client_order_id_deterministic():
    a = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="long")
    b = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="long")
    assert a == b


def test_client_order_id_changes_with_side():
    a = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="long")
    b = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="short")
    assert a != b


def test_client_order_id_length_and_charset():
    cid = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="long")
    assert len(cid) <= 36
    assert cid.replace("-", "").replace("_", "").isalnum()

