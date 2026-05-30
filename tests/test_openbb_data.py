"""Tests for OpenBB symbol mapping and OHLCV normalization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
from quant_rd_tool import openbb_data as obb


def test_to_openbb_symbol_shanghai():
    assert obb.to_openbb_symbol("600519") == "600519.SS"
    assert obb.to_openbb_symbol("SH600519") == "600519.SS"


def test_to_openbb_symbol_shenzhen():
    assert obb.to_openbb_symbol("000858") == "000858.SZ"


def test_normalize_openbb_df():
    raw = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "open": [10.0, 10.5],
            "high": [10.2, 10.8],
            "low": [9.8, 10.3],
            "close": [10.1, 10.6],
            "volume": [1000, 1100],
        }
    )
    out = obb._normalize_openbb_df(raw, "SH600519")
    assert list(out.columns) == ["date", "symbol", "open", "high", "low", "close", "volume"]
    assert out["symbol"].iloc[0] == "SH600519"
    assert len(out) == 2


@patch("quant_rd_tool.openbb_data.openbb_available", return_value=True)
def test_fetch_stock_daily_openbb(_mock_avail):
    fake_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "open": [10.0, 10.5],
            "high": [10.2, 10.8],
            "low": [9.8, 10.3],
            "close": [10.1, 10.6],
            "volume": [1000, 1100],
        }
    )
    mock_result = MagicMock()
    mock_result.to_df.return_value = fake_df
    mock_obb = MagicMock()
    mock_obb.equity.price.historical.return_value = mock_result

    with patch("openbb.obb", mock_obb):
        out = obb.fetch_stock_daily(
            "600519",
            start_date="2024-01-01",
            end_date="2024-01-31",
            provider="yfinance",
        )
    assert len(out) == 2
    assert out["symbol"].iloc[0] == "SH600519"
    mock_obb.equity.price.historical.assert_called()


def test_fetch_company_news_empty_on_failure():
    with patch("quant_rd_tool.openbb_data.openbb_available", return_value=True):
        with patch("openbb.obb") as mock_obb:
            mock_obb.news.company.side_effect = RuntimeError("no key")
            assert obb.fetch_company_news("600519") == []
