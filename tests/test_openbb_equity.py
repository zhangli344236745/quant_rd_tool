"""Tests for OpenBB equity overlay and research bundle."""

from __future__ import annotations

import pandas as pd

from quant_rd_tool.openbb_equity import compute_technical_overlay
from quant_rd_tool.openbb_research import build_openbb_research


def _ohlcv():
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    close = pd.Series(range(100, 160), index=dates, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": 1_000_000,
            "symbol": "SH600519",
        }
    )


def test_compute_technical_overlay():
    out = compute_technical_overlay(_ohlcv())
    assert "macd" in out
    assert "bollinger" in out
    assert out["macd"]["trend"] in ("MACD 多头", "MACD 空头", "中性")


def test_build_openbb_research_mock():
    from unittest.mock import patch

    fake = {
        "available": True,
        "summary": "测试",
        "macro": {"available": True, "summary": "宏观"},
        "news": [],
    }
    with patch("quant_rd_tool.openbb_research.openbb_available", return_value=True):
        with patch("quant_rd_tool.openbb_research.configure_openbb_credentials", return_value={}):
            with patch("quant_rd_tool.openbb_research.fetch_equity_snapshot", return_value=None):
                with patch("quant_rd_tool.openbb_research.fetch_company_news", return_value=[]):
                    with patch("quant_rd_tool.openbb_research.fetch_fundamentals", return_value={}):
                        with patch("quant_rd_tool.openbb_research.fetch_estimates", return_value={}):
                            with patch(
                                "quant_rd_tool.openbb_research.fetch_equity_calendar",
                                return_value={},
                            ):
                                with patch(
                                    "quant_rd_tool.openbb_research.fetch_economy_calendar_events",
                                    return_value=[],
                                ):
                                    with patch(
                                        "quant_rd_tool.openbb_research.fetch_cross_asset_fx",
                                        return_value=None,
                                    ):
                                        with patch(
                                            "quant_rd_tool.openbb_research.fetch_macro_context",
                                            return_value=fake["macro"],
                                        ):
                                            with patch(
                                                "quant_rd_tool.openbb_research.fetch_industry_context",
                                                return_value={"available": True},
                                            ):
                                                with patch(
                                                    "quant_rd_tool.openbb_research.probe_capabilities",
                                                    return_value={"features": []},
                                                ):
                                                    out = build_openbb_research(
                                                        "600519", ohlcv=_ohlcv()
                                                    )
    assert out["available"]
    assert out.get("technical_overlay")
