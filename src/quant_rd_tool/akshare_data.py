"""Fetch A-share OHLCV via akshare (multi-source fallback) and normalize for qlib."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from typing import TypeVar

import akshare as ak
import pandas as pd

from quant_rd_tool.stock_codes import to_ak_code, to_market_prefixed_symbol, to_qlib_code

logger = logging.getLogger(__name__)

T = TypeVar("T")

_AK_COL_MAP = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "涨跌幅": "change_pct",
    "换手率": "turnover",
}

# East Money 接口易限流/断连，请求超时（秒）
_EM_TIMEOUT = 30


def _retry(
    call: Callable[[], T],
    *,
    attempts: int = 3,
    delay: float = 2.0,
    source: str = "",
) -> T:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return call()
        except Exception as e:
            last = e
            if source:
                logger.warning("akshare %s attempt %s/%s failed: %s", source, i + 1, attempts, e)
            if i < attempts - 1:
                time.sleep(delay * (i + 1))
    assert last is not None
    raise last


def _canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for col in df.columns:
        if col in _AK_COL_MAP:
            rename[col] = _AK_COL_MAP[col]
        elif isinstance(col, str) and col.lower() in (
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ):
            rename[col] = col.lower()
    return df.rename(columns=rename)


def _filter_date_range(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return out[(out["date"] >= start) & (out["date"] <= end)]


def _normalize_hist(df: pd.DataFrame, qlib_code: str) -> pd.DataFrame:
    out = _canonical_columns(df).copy()
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = qlib_code
    if "volume" not in out.columns and "amount" in out.columns:
        out["volume"] = out["amount"]
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    keep = ["date", "symbol", "open", "high", "low", "close", "volume"]
    if "amount" in out.columns:
        keep.append("amount")
    if "change_pct" in out.columns:
        keep.append("change_pct")
    return out[keep].dropna(subset=["close"]).sort_values("date")


def _fetch_em(ak_code: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    return ak.stock_zh_a_hist(
        symbol=ak_code,
        period="daily",
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust=adjust,
        timeout=_EM_TIMEOUT,
    )


def _fetch_tx(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    tx_symbol = to_market_prefixed_symbol(symbol)
    return ak.stock_zh_a_hist_tx(
        symbol=tx_symbol,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust=adjust,
        timeout=_EM_TIMEOUT,
    )


def _fetch_sina(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    sina_symbol = to_market_prefixed_symbol(symbol)
    return ak.stock_zh_a_daily(
        symbol=sina_symbol,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust=adjust,
    )


def fetch_stock_daily(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """Download one A-share daily series; tries East Money → Tencent → Sina."""
    ak_code = to_ak_code(symbol)
    qlib_code = to_qlib_code(symbol)
    errors: list[str] = []

    sources: list[tuple[str, Callable[[], pd.DataFrame]]] = [
        ("eastmoney", lambda: _fetch_em(ak_code, start_date, end_date, adjust)),
        ("tencent", lambda: _fetch_tx(symbol, start_date, end_date, adjust)),
        ("sina", lambda: _fetch_sina(symbol, start_date, end_date, adjust)),
    ]

    raw: pd.DataFrame | None = None
    used_source = ""
    for name, fetcher in sources:
        try:
            raw = _retry(fetcher, attempts=3, delay=2.5, source=name)
            if raw is not None and not raw.empty:
                used_source = name
                break
            errors.append(f"{name}: empty result")
        except Exception as e:
            errors.append(f"{name}: {e}")
            time.sleep(1.0)

    if raw is None or raw.empty:
        detail = "; ".join(errors) if errors else "unknown"
        msg = (
            f"无法获取 {symbol!r} 行情（{start_date} ~ {end_date}）。"
            f"东方财富接口可能限流或断连，已尝试备用源仍失败。详情: {detail}"
        )
        raise ConnectionError(msg)

    if used_source:
        logger.info("Fetched %s via akshare source=%s", qlib_code, used_source)

    normalized = _normalize_hist(_filter_date_range(raw, start_date, end_date), qlib_code)
    if normalized.empty:
        msg = f"No rows for {symbol!r} between {start_date} and {end_date} after filtering."
        raise ValueError(msg)
    return normalized


def fetch_index_daily(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Download index daily bars; ak symbol sh000300 → qlib SH000300."""
    s = symbol.strip().lower()
    if not s.startswith(("sh", "sz")):
        s = f"sh{s}"
    raw = _retry(lambda: ak.stock_zh_index_daily(symbol=s), source="sina_index")
    if raw is None or raw.empty:
        msg = f"No index data for {symbol!r}."
        raise ValueError(msg)
    raw["date"] = pd.to_datetime(raw["date"])
    mask = (raw["date"] >= pd.Timestamp(start_date)) & (raw["date"] <= pd.Timestamp(end_date))
    raw = raw.loc[mask]
    if s.startswith("sh"):
        qlib_code = "SH" + s[2:].upper()
    else:
        qlib_code = "SZ" + s[2:].upper()
    out = raw.rename(
        columns={"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
    )
    out["symbol"] = qlib_code
    cols = ["date", "symbol", "open", "high", "low", "close", "volume"]
    return out[cols].dropna(subset=["close"])


def fetch_universe(
    symbols: Iterable[str],
    *,
    start_date: str,
    end_date: str,
    benchmark: str = "sh000300",
) -> dict[str, pd.DataFrame]:
    """Return {qlib_code: ohlcv_df} for stocks plus optional benchmark index."""
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols):
        if i:
            time.sleep(1.2)
        code = to_qlib_code(sym)
        frames[code] = fetch_stock_daily(sym, start_date=start_date, end_date=end_date)
    try:
        time.sleep(0.8)
        bench = fetch_index_daily(benchmark, start_date=start_date, end_date=end_date)
        frames[bench["symbol"].iloc[0]] = bench
    except (ValueError, OSError, ConnectionError):
        pass
    return frames


def default_demo_universe() -> list[str]:
    """Liquid large-cap names for a quick demo."""
    return ["600519", "000858", "601318", "600036", "000001"]
