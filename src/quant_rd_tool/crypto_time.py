"""Beijing (Asia/Shanghai) display time for crypto OHLCV."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd

BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def ms_to_beijing_naive(ms: int) -> pd.Timestamp:
    """UTC epoch ms → naive wall-clock in Beijing."""
    return pd.to_datetime(int(ms), unit="ms", utc=True).tz_convert(BEIJING_TZ).tz_localize(None)


def ms_to_beijing_str(ms: int, *, with_seconds: bool = True) -> str:
    ts = ms_to_beijing_naive(ms)
    if with_seconds:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return ts.strftime("%Y-%m-%d")


def utc_now_beijing_str(*, with_seconds: bool = True) -> str:
    now = datetime.now(BEIJING_TZ)
    if with_seconds:
        return now.strftime("%Y-%m-%d %H:%M:%S")
    return now.strftime("%Y-%m-%d")


def normalize_ohlcv_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure ``timestamp`` (UTC ms) and ``date`` (Beijing naive) columns are consistent.

    When ``timestamp`` exists it is authoritative (fixes legacy CSV with UTC ``date``).
    """
    cols = ["timestamp", "date", "symbol", "open", "high", "low", "close", "volume"]
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    if "timestamp" in out.columns and out["timestamp"].notna().all():
        out["timestamp"] = out["timestamp"].astype("int64")
    else:
        out["timestamp"] = out["date"].map(
            lambda d: int(pd.Timestamp(d, tz="UTC").timestamp() * 1000)
        ).astype("int64")
    out["date"] = out["timestamp"].map(ms_to_beijing_naive)
    return out[cols]
