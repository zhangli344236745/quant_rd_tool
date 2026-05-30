"""Tests for unified market_data provider routing."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from quant_rd_tool import market_data as mkt


def _sample_df():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02"]),
            "symbol": ["SH600519"],
            "open": [10.0],
            "high": [10.2],
            "low": [9.8],
            "close": [10.1],
            "volume": [1000],
        }
    )


def test_fetch_stock_daily_akshare_only():
    with patch("quant_rd_tool.akshare_data.fetch_stock_daily", return_value=_sample_df()) as ak:
        out = mkt.fetch_stock_daily(
            "600519",
            start_date="2024-01-01",
            end_date="2024-01-31",
            provider="akshare",
        )
        ak.assert_called_once()
        assert len(out) == 1


def test_auto_falls_back_to_openbb():
    with patch(
        "quant_rd_tool.akshare_data.fetch_stock_daily",
        side_effect=ConnectionError("ak down"),
    ):
        with patch("quant_rd_tool.openbb_data.openbb_available", return_value=True):
            with patch(
                "quant_rd_tool.openbb_data.fetch_stock_daily",
                return_value=_sample_df(),
            ) as obb_fetch:
                out = mkt.fetch_stock_daily(
                    "600519",
                    start_date="2024-01-01",
                    end_date="2024-01-31",
                    provider="auto",
                )
                obb_fetch.assert_called_once()
                assert len(out) == 1
