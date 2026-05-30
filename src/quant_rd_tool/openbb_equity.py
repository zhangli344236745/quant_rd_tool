"""OpenBB equity research: fundamentals, estimates, calendar, extended technicals."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from quant_rd_tool.openbb_data import openbb_available, to_openbb_symbol

logger = logging.getLogger(__name__)


def _row_dict(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        return {}
    row = df.iloc[-1] if len(df) == 1 else df.iloc[0]
    out: dict[str, Any] = {}
    for k, v in row.items():
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        if isinstance(v, (int, float, str, bool)):
            out[str(k)] = v
        else:
            out[str(k)] = str(v)
    return out


def _try_obb(callable_fn, *, label: str) -> dict[str, Any] | list[Any] | None:
    try:
        result = callable_fn()
        if hasattr(result, "to_df"):
            df = result.to_df()
            if df is None or df.empty:
                return None
            if len(df) == 1:
                return _row_dict(df)
            return df.to_dict(orient="records")[:12]
        rows = getattr(result, "results", None)
        if rows:
            out = []
            for r in rows[:12]:
                out.append(r.model_dump() if hasattr(r, "model_dump") else dict(r))
            return out
        return None
    except Exception as e:
        logger.debug("OpenBB %s: %s", label, e)
        return None


def compute_technical_overlay(df: pd.DataFrame) -> dict[str, Any]:
    """MACD / Bollinger / ATR from local OHLCV (complements stock_analyzer RSI/MA)."""
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values("date")
    close = work["close"].astype(float)
    high = work["high"].astype(float)
    low = work["low"].astype(float)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal

    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    upper = mid + 2 * std
    lower = mid - 2 * std

    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr14 = tr.rolling(14).mean()

    latest_close = float(close.iloc[-1])
    bb_pos = None
    if pd.notna(upper.iloc[-1]) and pd.notna(lower.iloc[-1]) and upper.iloc[-1] != lower.iloc[-1]:
        bb_pos = float((latest_close - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]))

    macd_last = float(macd_line.iloc[-1]) if pd.notna(macd_line.iloc[-1]) else None
    signal_last = float(signal.iloc[-1]) if pd.notna(signal.iloc[-1]) else None
    hist_last = float(hist.iloc[-1]) if pd.notna(hist.iloc[-1]) else None

    trend = "中性"
    if macd_last is not None and signal_last is not None:
        if macd_last > signal_last and hist_last and hist_last > 0:
            trend = "MACD 多头"
        elif macd_last < signal_last and hist_last and hist_last < 0:
            trend = "MACD 空头"

    bb_zone = "中轨附近"
    if bb_pos is not None:
        if bb_pos > 0.8:
            bb_zone = "接近布林上轨（偏强/超买）"
        elif bb_pos < 0.2:
            bb_zone = "接近布林下轨（偏弱/超卖）"

    return {
        "macd": {"line": macd_last, "signal": signal_last, "histogram": hist_last, "trend": trend},
        "bollinger": {
            "upper": float(upper.iloc[-1]) if pd.notna(upper.iloc[-1]) else None,
            "middle": float(mid.iloc[-1]) if pd.notna(mid.iloc[-1]) else None,
            "lower": float(lower.iloc[-1]) if pd.notna(lower.iloc[-1]) else None,
            "position": bb_pos,
            "zone": bb_zone,
        },
        "atr14": float(atr14.iloc[-1]) if pd.notna(atr14.iloc[-1]) else None,
    }


def fetch_fundamentals(symbol: str) -> dict[str, Any]:
    """Ratios / metrics when provider credentials allow."""
    if not openbb_available():
        return {}

    import os

    from openbb import obb

    obb_sym = to_openbb_symbol(symbol)
    out: dict[str, Any] = {}

    if os.environ.get("FMP_API_KEY"):
        ratios = _try_obb(
            lambda: obb.equity.fundamental.ratios(symbol=obb_sym, provider="fmp"),
            label="ratios",
        )
        if ratios:
            out["ratios"] = ratios

    metrics = _try_obb(
        lambda: obb.equity.fundamental.metrics(symbol=obb_sym, provider="yfinance"),
        label="metrics",
    )
    if not metrics and os.environ.get("FMP_API_KEY"):
        metrics = _try_obb(
            lambda: obb.equity.fundamental.metrics(symbol=obb_sym, provider="fmp"),
            label="metrics_fmp",
        )
    if metrics:
        out["metrics"] = metrics

    return out


def fetch_estimates(symbol: str) -> dict[str, Any]:
    if not openbb_available() or not __import__("os").environ.get("FMP_API_KEY"):
        return {}

    from openbb import obb

    obb_sym = to_openbb_symbol(symbol)
    out: dict[str, Any] = {}
    consensus = _try_obb(
        lambda: obb.equity.estimates.consensus(symbol=obb_sym, provider="fmp"),
        label="consensus",
    )
    if consensus:
        out["consensus"] = consensus
    targets = _try_obb(
        lambda: obb.equity.estimates.price_target(symbol=obb_sym, provider="fmp"),
        label="price_target",
    )
    if targets:
        out["price_targets"] = targets
    return out


def fetch_equity_calendar(symbol: str) -> dict[str, Any]:
    if not openbb_available() or not __import__("os").environ.get("FMP_API_KEY"):
        return {}

    from openbb import obb

    obb_sym = to_openbb_symbol(symbol)
    out: dict[str, Any] = {}
    earnings = _try_obb(
        lambda: obb.equity.calendar.earnings(symbol=obb_sym, provider="fmp"),
        label="earnings",
    )
    if earnings:
        out["earnings"] = earnings
    dividends = _try_obb(
        lambda: obb.equity.calendar.dividend(symbol=obb_sym, provider="fmp"),
        label="dividend",
    )
    if dividends:
        out["dividends"] = dividends
    return out


def fetch_economy_calendar_events(*, country: str = "china", limit: int = 8) -> list[dict[str, Any]]:
    """Upcoming macro events (FMP / TradingEconomics when keyed)."""
    import os

    if not openbb_available():
        return []

    from openbb import obb

    for prov, kwargs in (
        ("fmp", {"country": "CN"}),
        ("tradingeconomics", {"country": "china"}),
    ):
        env = "FMP_API_KEY" if prov == "fmp" else "TRADINGECONOMICS_API_KEY"
        if not os.environ.get(env):
            continue
        try:
            result = obb.economy.calendar(provider=prov, **kwargs)
            df = result.to_df()
            if df is None or df.empty:
                continue
            rows = df.head(limit).to_dict(orient="records")
            return [{str(k): v for k, v in r.items()} for r in rows]
        except Exception as e:
            logger.debug("economy.calendar %s: %s", prov, e)
    return []


def fetch_cross_asset_fx(
    *,
    pair: str = "USDCNY",
    start_date: str = "2024-01-01",
    end_date: str | None = None,
) -> dict[str, Any] | None:
    if not openbb_available():
        return None

    from datetime import date

    from openbb import obb

    end = end_date or date.today().isoformat()
    for sym in (f"{pair}=X", pair, "CNY=X"):
        try:
            result = obb.currency.price.historical(
                symbol=sym,
                start_date=start_date,
                end_date=end,
                provider="yfinance",
            )
            df = result.to_df()
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None
            close_col = "close" if "close" in df.columns else df.columns[-1]
            val = float(last[close_col])
            chg = None
            if prev is not None:
                pv = float(prev[close_col])
                if pv:
                    chg = (val - pv) / pv
            return {"symbol": sym, "date": str(df.index[-1])[:10], "rate": val, "change_pct": chg}
        except Exception as e:
            logger.debug("fx %s: %s", sym, e)
    return None
