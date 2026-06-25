from unittest.mock import MagicMock, patch

from quant_rd_tool.perp_account_analytics import _with_retry, fetch_recent_trades


def test_with_retry_succeeds_after_transient_failure():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise Exception("429 Too Many Requests")
        return "ok"

    assert _with_retry(fn, attempts=3) == "ok"
    assert calls["n"] == 2


def test_fetch_recent_trades_returns_error_instead_of_raising():
    mock_ex = MagicMock()
    mock_ex.fetch_my_trades.side_effect = RuntimeError("network timeout")

    with patch("quant_rd_tool.perp_account_analytics._exchange", return_value=mock_ex):
        result = fetch_recent_trades(base="ETH", limit=10, testnet=False)

    assert result["enabled"] is True
    assert result["items"] == []
    assert "timeout" in result["error"].lower()
    mock_ex.close.assert_called()
