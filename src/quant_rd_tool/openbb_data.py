"""OpenBB ODP wrappers for A-share OHLCV and optional research enrichment."""

from __future__ import annotations

import logging
from typing import Any, Literal

import pandas as pd

from quant_rd_tool import akshare_data as ak_data

logger = logging.getLogger(__name__)

OpenBBPriceProvider = Literal["yfinance", "fmp", "polygon", "tiingo"]

_OBB_COL_MAP = {
    "date": "date",
    "datetime": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "adj_close": "adj_close",
}


def openbb_available() -> bool:
    try:
        import openbb  # noqa: F401

        return True
    except ImportError:
        return False


def to_openbb_symbol(symbol: str) -> str:
    """Map bare / qlib code to Yahoo-style ticker (600519.SS, 000858.SZ)."""
    s = symbol.strip().upper()
    if s.endswith((".SS", ".SZ", ".HK")):
        return s
    code = ak_data.to_ak_code(s)
    if code.startswith("6") or code.startswith("9"):
        return f"{code}.SS"
    return f"{code}.SZ"


def _openbb_symbol_candidates(symbol: str) -> list[str]:
    primary = to_openbb_symbol(symbol)
    ak_code = ak_data.to_ak_code(symbol)
    candidates = [primary]
    if ak_code != primary.split(".")[0]:
        candidates.append(ak_code)
    return list(dict.fromkeys(candidates))


def _normalize_openbb_df(df: pd.DataFrame, qlib_code: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    out.columns = [str(c).lower().strip() for c in out.columns]
    for src, dst in _OBB_COL_MAP.items():
        if src in out.columns and dst not in out.columns:
            out = out.rename(columns={src: dst})

    if "date" not in out.columns and isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index().rename(columns={"index": "date", "datetime": "date"})

    if "date" not in out.columns:
        for col in out.columns:
            if "date" in col:
                out = out.rename(columns={col: "date"})
                break

    if "date" not in out.columns:
        return pd.DataFrame()

    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = qlib_code
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    keep = ["date", "symbol", "open", "high", "low", "close", "volume"]
    return out[keep].dropna(subset=["close"]).sort_values("date")


def fetch_stock_daily(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    provider: OpenBBPriceProvider = "yfinance",
) -> pd.DataFrame:
    """Download daily OHLCV via OpenBB ``obb.equity.price.historical``."""
    if not openbb_available():
        msg = "OpenBB 未安装。请运行: uv sync"
        raise ImportError(msg)

    from openbb import obb

    qlib_code = ak_data.to_qlib_code(symbol)
    errors: list[str] = []

    for obb_sym in _openbb_symbol_candidates(symbol):
        try:
            result = obb.equity.price.historical(
                symbol=obb_sym,
                start_date=start_date,
                end_date=end_date,
                provider=provider,
            )
            df = result.to_df()
            normalized = _normalize_openbb_df(df, qlib_code)
            if normalized.empty:
                errors.append(f"{obb_sym}: empty")
                continue
            mask = (normalized["date"] >= pd.Timestamp(start_date)) & (
                normalized["date"] <= pd.Timestamp(end_date)
            )
            normalized = normalized.loc[mask]
            if normalized.empty:
                errors.append(f"{obb_sym}: no rows in range")
                continue
            logger.info(
                "Fetched %s via openbb provider=%s symbol=%s",
                qlib_code,
                provider,
                obb_sym,
            )
            return normalized
        except Exception as e:
            errors.append(f"{obb_sym}: {e}")

    detail = "; ".join(errors) if errors else "unknown"
    msg = (
        f"OpenBB 无法获取 {symbol!r} 行情（{start_date} ~ {end_date}，provider={provider}）。"
        f"详情: {detail}"
    )
    raise ConnectionError(msg)


def fetch_company_news(
    symbol: str,
    *,
    limit: int = 8,
    providers: tuple[str, ...] = ("yfinance", "fmp"),
) -> list[dict[str, Any]]:
    """Best-effort company news via OpenBB; returns [] if no credentials / data."""
    if not openbb_available():
        return []

    from openbb import obb

    obb_sym = to_openbb_symbol(symbol)
    items: list[dict[str, Any]] = []

    for prov in providers:
        try:
            result = obb.news.company(symbol=obb_sym, provider=prov, limit=limit)
            rows = getattr(result, "results", None) or []
            for row in rows[:limit]:
                title = getattr(row, "title", None) or (row.get("title") if isinstance(row, dict) else None)
                if not title:
                    continue
                items.append(
                    {
                        "title": str(title),
                        "date": str(getattr(row, "date", None) or getattr(row, "published", "") or ""),
                        "url": str(getattr(row, "url", None) or getattr(row, "link", "") or ""),
                        "provider": prov,
                    }
                )
            if items:
                return items[:limit]
        except Exception as e:
            logger.debug("OpenBB news provider=%s failed: %s", prov, e)

    return items


def fetch_equity_snapshot(symbol: str, *, provider: str = "yfinance") -> dict[str, Any] | None:
    """Company profile / snapshot when the provider returns data."""
    if not openbb_available():
        return None

    from openbb import obb

    obb_sym = to_openbb_symbol(symbol)
    try:
        result = obb.equity.profile(symbol=obb_sym, provider=provider)
    except Exception as e:
        logger.debug("OpenBB profile failed: %s", e)
        return None

    rows = getattr(result, "results", None)
    if not rows:
        df = result.to_df() if hasattr(result, "to_df") else None
        if df is None or df.empty:
            return None
        row = df.iloc[0].to_dict()
    else:
        r0 = rows[0]
        row = r0.model_dump() if hasattr(r0, "model_dump") else dict(r0)

    keep = (
        "name",
        "symbol",
        "exchange",
        "sector",
        "industry",
        "country",
        "currency",
        "market_cap",
        "employees",
        "description",
    )
    return {k: row[k] for k in keep if k in row and row[k] is not None}
