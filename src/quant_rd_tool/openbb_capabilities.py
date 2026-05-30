"""OpenBB capability registry and runtime probe for quant-rd-tool."""

from __future__ import annotations

import os
from typing import Any

from quant_rd_tool.openbb_data import openbb_available

# Features we integrate; ``probe`` fills ``available`` at runtime.
OPENBB_FEATURES: list[dict[str, Any]] = [
    {
        "id": "equity.price.historical",
        "category": "行情",
        "endpoint": "obb.equity.price.historical",
        "providers": ["yfinance", "fmp", "polygon"],
        "env": [],
        "integrated_in": ["market_data", "analyze", "backtest"],
    },
    {
        "id": "equity.profile",
        "category": "基本面",
        "endpoint": "obb.equity.profile",
        "providers": ["yfinance", "fmp"],
        "env": [],
        "integrated_in": ["analyze", "openbb_research"],
    },
    {
        "id": "equity.fundamental.ratios",
        "category": "基本面",
        "endpoint": "obb.equity.fundamental.ratios",
        "providers": ["fmp"],
        "env": ["FMP_API_KEY"],
        "integrated_in": ["analyze", "openbb_research"],
    },
    {
        "id": "equity.fundamental.metrics",
        "category": "基本面",
        "endpoint": "obb.equity.fundamental.metrics",
        "providers": ["yfinance", "fmp"],
        "env": [],
        "integrated_in": ["openbb_research"],
    },
    {
        "id": "equity.estimates.consensus",
        "category": "估值预期",
        "endpoint": "obb.equity.estimates.consensus",
        "providers": ["fmp"],
        "env": ["FMP_API_KEY"],
        "integrated_in": ["openbb_research"],
    },
    {
        "id": "equity.estimates.price_target",
        "category": "估值预期",
        "endpoint": "obb.equity.estimates.price_target",
        "providers": ["fmp"],
        "env": ["FMP_API_KEY"],
        "integrated_in": ["openbb_research"],
    },
    {
        "id": "equity.calendar.earnings",
        "category": "事件日历",
        "endpoint": "obb.equity.calendar.earnings",
        "providers": ["fmp"],
        "env": ["FMP_API_KEY"],
        "integrated_in": ["openbb_research"],
    },
    {
        "id": "equity.calendar.dividend",
        "category": "事件日历",
        "endpoint": "obb.equity.calendar.dividend",
        "providers": ["fmp"],
        "env": ["FMP_API_KEY"],
        "integrated_in": ["openbb_research"],
    },
    {
        "id": "equity.compare.peers",
        "category": "行业",
        "endpoint": "obb.equity.compare.peers",
        "providers": ["fmp"],
        "env": ["FMP_API_KEY"],
        "integrated_in": ["macro", "analyze"],
    },
    {
        "id": "news.company",
        "category": "新闻",
        "endpoint": "obb.news.company",
        "providers": ["yfinance", "fmp"],
        "env": [],
        "integrated_in": ["analyze"],
    },
    {
        "id": "economy.country_profile",
        "category": "宏观",
        "endpoint": "obb.economy.country_profile",
        "providers": ["econdb"],
        "env": [],
        "integrated_in": ["macro", "analyze"],
    },
    {
        "id": "economy.indicators",
        "category": "宏观",
        "endpoint": "obb.economy.indicators",
        "providers": ["econdb"],
        "env": [],
        "integrated_in": ["macro", "analyze"],
    },
    {
        "id": "economy.fred_series",
        "category": "宏观",
        "endpoint": "obb.economy.fred_series",
        "providers": ["fred"],
        "env": ["FRED_API_KEY"],
        "integrated_in": ["macro", "analyze"],
    },
    {
        "id": "economy.share_price_index",
        "category": "宏观",
        "endpoint": "obb.economy.share_price_index",
        "providers": ["oecd"],
        "env": [],
        "integrated_in": ["macro"],
    },
    {
        "id": "economy.calendar",
        "category": "宏观",
        "endpoint": "obb.economy.calendar",
        "providers": ["fmp", "tradingeconomics"],
        "env": ["FMP_API_KEY", "TRADINGECONOMICS_API_KEY"],
        "integrated_in": ["openbb_research"],
    },
    {
        "id": "currency.price.historical",
        "category": "跨资产",
        "endpoint": "obb.currency.price.historical",
        "providers": ["yfinance", "fmp"],
        "env": [],
        "integrated_in": ["openbb_research"],
    },
    {
        "id": "derivatives.futures.historical",
        "category": "跨资产",
        "endpoint": "obb.derivatives.futures.historical",
        "providers": ["yfinance", "fmp"],
        "env": [],
        "integrated_in": [],
    },
    {
        "id": "local.technical_overlay",
        "category": "技术面",
        "endpoint": "local OHLCV → MACD/布林带/ATR",
        "providers": ["internal"],
        "env": [],
        "integrated_in": ["analyze", "openbb_research"],
    },
    {
        "id": "crypto.qlib_ml",
        "category": "加密货币",
        "endpoint": "qlib Alpha158 + XGB/LGB on CRYPTO_*",
        "providers": ["qlib"],
        "env": [],
        "integrated_in": ["crypto analyze", "crypto ml", "crypto bot --use-ml"],
    },
]


def credential_status() -> dict[str, bool]:
    return {
        "fred": bool(os.environ.get("FRED_API_KEY")),
        "fmp": bool(os.environ.get("FMP_API_KEY")),
        "tradingeconomics": bool(os.environ.get("TRADINGECONOMICS_API_KEY")),
        "econdb": bool(os.environ.get("ECONDB_API_KEY")),
    }


def list_capabilities(*, integrated_only: bool = False) -> dict[str, Any]:
    creds = credential_status()
    features = []
    for row in OPENBB_FEATURES:
        item = dict(row)
        needs = row.get("env") or []
        item["credentials_ok"] = all(creds.get(k.replace("_API_KEY", "").lower(), True) for k in needs) if needs else True
        if integrated_only and not row.get("integrated_in"):
            continue
        features.append(item)
    return {
        "openbb_installed": openbb_available(),
        "credentials": creds,
        "features": features,
        "categories": sorted({f["category"] for f in features}),
    }


def probe_capabilities() -> dict[str, Any]:
    """Light probe: mark features reachable given install + env."""
    base = list_capabilities()
    if not base["openbb_installed"]:
        return {**base, "probed": False}

    creds = base["credentials"]
    for item in base["features"]:
        env_req = item.get("env") or []
        if env_req:
            item["available"] = all(os.environ.get(k) for k in env_req)
        elif item["id"] == "economy.country_profile":
            item["available"] = True
        elif item["id"] == "local.technical_overlay":
            item["available"] = True
        elif "fmp" in item.get("providers", []) and not creds.get("fred") and item["id"].startswith("economy.fred"):
            item["available"] = creds.get("fred", False)
        elif "fmp" in item.get("providers", []) and env_req == []:
            item["available"] = True
        else:
            item["available"] = item["id"] in {
                "equity.price.historical",
                "equity.profile",
                "news.company",
                "economy.country_profile",
                "economy.indicators",
                "economy.share_price_index",
                "local.technical_overlay",
            } or creds.get("fmp", False)

    base["probed"] = True
    return base
