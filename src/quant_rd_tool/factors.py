"""Price-based factor helpers (yfinance → pandas)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    safe_loss = avg_loss.replace(0, np.nan)
    rs = avg_gain / safe_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return rsi


def fetch_ohlcv(
    symbol: str,
    *,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    t = yf.Ticker(symbol)
    df = t.history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        msg = f"No OHLCV data for symbol={symbol!r} (period={period}, interval={interval})."
        raise ValueError(msg)
    return df


def compute_factors(
    df: pd.DataFrame,
    *,
    momentum_windows: tuple[int, ...] = (5, 20, 60),
    vol_window: int = 20,
) -> dict[str, Any]:
    """Return latest snapshot + recent series tail for common factors."""
    close = df["Close"].astype(float)
    ret_1d = close.pct_change()
    out: dict[str, Any] = {"as_of": str(close.index[-1].date()) if len(close) else None}

    for w in momentum_windows:
        key = f"mom_{w}d"
        mom = close.pct_change(w)
        out[key] = float(mom.iloc[-1]) if pd.notna(mom.iloc[-1]) else None

    vol = ret_1d.rolling(vol_window).std() * np.sqrt(252)
    out[f"realized_vol_{vol_window}d_ann"] = (
        float(vol.iloc[-1]) if pd.notna(vol.iloc[-1]) else None
    )

    rsi = _rsi(close)
    out["rsi_14"] = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else None

    sma20 = close.rolling(20).mean()
    out["close_vs_sma20"] = (
        float(close.iloc[-1] / sma20.iloc[-1] - 1) if pd.notna(sma20.iloc[-1]) else None
    )

    tail = min(30, len(df))
    out["series_tail"] = {
        "dates": [str(x.date()) for x in close.index[-tail:]],
        "close": [float(x) for x in close.iloc[-tail:]],
        "ret_1d": [float(x) if pd.notna(x) else None for x in ret_1d.iloc[-tail:]],
    }
    return out
