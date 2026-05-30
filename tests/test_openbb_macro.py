"""Tests for OpenBB macro / industry context."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from quant_rd_tool import openbb_macro as macro


def test_sector_bucket_consumer():
    assert macro._sector_bucket("Consumer Defensive", "Beverages") == "consumer"


def test_build_macro_summary():
    china = {
        "profile": {"gdp_yoy": 0.04, "cpi_yoy": -0.02, "policy_rate": 0.035},
        "label": "中国",
    }
    global_ref = [{"label": "美国", "profile": {"gdp_yoy": 0.026}}]
    text = macro._build_macro_summary(china, global_ref)
    assert "中国" in text
    assert "美国" in text


@patch("quant_rd_tool.openbb_macro.openbb_available", return_value=True)
def test_fetch_macro_context_mock(_avail):
    prof_df = pd.DataFrame(
        [
            {
                "gdp_yoy": 0.04,
                "cpi_yoy": 0.01,
                "policy_rate": 0.03,
            }
        ]
    )
    ind_df = pd.DataFrame({"value": [100.0, 101.0]}, index=pd.to_datetime(["2026-01-01", "2026-02-01"]))

    mock_obb = MagicMock()
    mock_obb.economy.country_profile.return_value.to_df.return_value = prof_df
    mock_obb.economy.indicators.return_value.to_df.return_value = ind_df
    mock_obb.economy.share_price_index.return_value.to_df.return_value = ind_df

    with patch("openbb.obb", mock_obb):
        out = macro.fetch_macro_context(countries=("china",))

    assert out["available"] is True
    assert out["china"]["profile"]["gdp_yoy"] == 0.04
    assert out["summary"]


@patch("quant_rd_tool.openbb_macro.openbb_available", return_value=True)
@patch("quant_rd_tool.openbb_macro.fetch_country_macro_snapshot")
def test_fetch_industry_context(mock_snap, _avail):
    mock_snap.return_value = {
        "available": True,
        "profile": {
            "gdp_yoy": 0.04,
            "retail_sales_yoy": 0.03,
            "cpi_yoy": 0.01,
        },
    }
    profile = {"name": "茅台", "sector": "Consumer Defensive", "industry": "Beverages"}
    out = macro.fetch_industry_context("600519", profile=profile)
    assert out["available"] is True
    assert out["sector_bucket"] == "consumer"
    assert out["sector_macro_metrics"]
    assert "茅台" in out["interpretation"]
