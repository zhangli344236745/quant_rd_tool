from quant_rd_tool.binance_perp_bot import _normalize_position_rows


def test_normalize_flat():
    side, amt = _normalize_position_rows([{"contracts": 0.0}], position_epsilon=1e-12)
    assert side == "flat"
    assert amt == 0.0


def test_normalize_long():
    side, amt = _normalize_position_rows([{"contracts": 0.1}], position_epsilon=1e-12)
    assert side == "long"
    assert amt == 0.1


def test_normalize_short():
    side, amt = _normalize_position_rows([{"contracts": -0.2}], position_epsilon=1e-12)
    assert side == "short"
    assert amt == 0.2


def test_reject_multiple_rows():
    try:
        _normalize_position_rows([{"contracts": 0.1}, {"contracts": -0.1}], position_epsilon=1e-12)
    except ValueError as e:
        msg = str(e).lower()
        assert "hedge" in msg or "multiple" in msg or "多行" in msg
    else:
        raise AssertionError("expected ValueError")

