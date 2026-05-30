"""Unified market data: akshare (primary) + OpenBB (fallback / enrichment)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Literal

import pandas as pd

from quant_rd_tool import akshare_data as ak_data
from quant_rd_tool import openbb_data as obb_data

logger = logging.getLogger(__name__)

DataProvider = Literal["auto", "akshare", "openbb"]


def fetch_stock_daily(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
    provider: DataProvider = "auto",
    openbb_provider: obb_data.OpenBBPriceProvider = "yfinance",
) -> pd.DataFrame:
    """
    Download one A-share daily series.

    - ``akshare``: East Money → Tencent → Sina (前复权)
    - ``openbb``: OpenBB historical (默认 yfinance，复权规则依数据源)
    - ``auto``: 先 akshare，失败再 OpenBB
    """
    if provider == "akshare":
        return ak_data.fetch_stock_daily(
            symbol, start_date=start_date, end_date=end_date, adjust=adjust
        )
    if provider == "openbb":
        return obb_data.fetch_stock_daily(
            symbol,
            start_date=start_date,
            end_date=end_date,
            provider=openbb_provider,
        )

    try:
        return ak_data.fetch_stock_daily(
            symbol, start_date=start_date, end_date=end_date, adjust=adjust
        )
    except (ConnectionError, ValueError) as ak_err:
        if not obb_data.openbb_available():
            raise ak_err
        logger.warning("akshare failed for %s, trying OpenBB: %s", symbol, ak_err)
        try:
            return obb_data.fetch_stock_daily(
                symbol,
                start_date=start_date,
                end_date=end_date,
                provider=openbb_provider,
            )
        except Exception as obb_err:
            msg = (
                f"行情获取失败：akshare ({ak_err}); OpenBB ({obb_err})。"
                "可稍后重试或使用本地 CSV。"
            )
            raise ConnectionError(msg) from obb_err


def fetch_universe(
    symbols: Iterable[str],
    *,
    start_date: str,
    end_date: str,
    benchmark: str = "sh000300",
    provider: DataProvider = "auto",
    openbb_provider: obb_data.OpenBBPriceProvider = "yfinance",
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols):
        if i:
            time.sleep(1.2)
        code = ak_data.to_qlib_code(sym)
        frames[code] = fetch_stock_daily(
            sym,
            start_date=start_date,
            end_date=end_date,
            provider=provider,
            openbb_provider=openbb_provider,
        )
    try:
        time.sleep(0.8)
        bench = ak_data.fetch_index_daily(benchmark, start_date=start_date, end_date=end_date)
        frames[bench["symbol"].iloc[0]] = bench
    except (ValueError, OSError, ConnectionError):
        pass
    return frames


def enrich_with_openbb(symbol: str, *, ohlcv: pd.DataFrame | None = None) -> dict:
    """Non-fatal OpenBB research bundle for reports."""
    from quant_rd_tool.openbb_research import build_openbb_research

    return build_openbb_research(symbol, ohlcv=ohlcv)


# Re-export helpers used across the codebase
to_qlib_code = ak_data.to_qlib_code
to_ak_code = ak_data.to_ak_code
to_openbb_symbol = obb_data.to_openbb_symbol
fetch_index_daily = ak_data.fetch_index_daily
default_demo_universe = ak_data.default_demo_universe
