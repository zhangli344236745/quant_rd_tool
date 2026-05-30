"""Tests for ccxt connectivity check (mocked, no network)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from quant_rd_tool.ccxt_connectivity import check_connectivity, require_connectivity
import pytest


def test_check_connectivity_ok():
    mock_ex = MagicMock()
    mock_ex.load_markets.return_value = {"BTC/USDT": {}}
    mock_ex.fetch_ohlcv.return_value = [[1, 1, 1, 1, 1, 1]]

    with patch("quant_rd_tool.ccxt_connectivity.cxt.create_exchange", return_value=mock_ex):
        report = check_connectivity("binance", symbol="BTC", timeframe="5m")
    assert report["ok"] is True
    assert len(report["steps"]) == 2
    mock_ex.close.assert_called_once()


def test_check_connectivity_markets_fail():
    mock_ex = MagicMock()
    mock_ex.load_markets.side_effect = Exception("exchangeInfo timeout")

    with patch("quant_rd_tool.ccxt_connectivity.cxt.create_exchange", return_value=mock_ex):
        report = check_connectivity("binance", test_ohlcv=False)
    assert report["ok"] is False
    assert report["steps"][0]["name"] == "load_markets"
    assert "hints" in report


def test_require_connectivity_raises():
    mock_ex = MagicMock()
    mock_ex.load_markets.side_effect = Exception("blocked")

    with patch("quant_rd_tool.ccxt_connectivity.cxt.create_exchange", return_value=mock_ex):
        with pytest.raises(ConnectionError, match="建议"):
            require_connectivity("binance", test_ohlcv=False)
