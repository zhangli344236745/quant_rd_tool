"""OpenBB macro & industry context for A-share research reports."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quant_rd_tool.openbb_data import openbb_available, to_openbb_symbol

logger = logging.getLogger(__name__)

# yfinance / OpenBB profile sector → econdb country_profile fields (YoY / levels)
_SECTOR_PROFILE_KEYS: dict[str, list[tuple[str, str]]] = {
    "consumer": [
        ("retail_sales_yoy", "社会零售同比"),
        ("cpi_yoy", "CPI 同比"),
    ],
    "financial": [
        ("policy_rate", "政策利率"),
        ("yield_10y", "10 年期国债收益率"),
    ],
    "industrial": [
        ("industrial_production_yoy", "工业增加值同比"),
        ("gdp_yoy", "GDP 同比"),
    ],
    "technology": [
        ("gdp_yoy", "GDP 同比"),
        ("industrial_production_yoy", "工业增加值同比"),
    ],
    "energy": [
        ("industrial_production_yoy", "工业增加值同比"),
        ("cpi_yoy", "CPI 同比"),
    ],
    "healthcare": [
        ("gdp_yoy", "GDP 同比"),
        ("cpi_yoy", "CPI 同比"),
    ],
    "real estate": [
        ("gdp_yoy", "GDP 同比"),
        ("yield_10y", "10 年期国债收益率"),
    ],
    "utilities": [
        ("policy_rate", "政策利率"),
        ("yield_10y", "10 年期国债收益率"),
    ],
    "default": [
        ("gdp_yoy", "GDP 同比"),
        ("cpi_yoy", "CPI 同比"),
        ("industrial_production_yoy", "工业增加值同比"),
    ],
}

# Extra econdb indicator series (symbol, frequency, label)
_SECTOR_ECONDB_SERIES: dict[str, list[tuple[str, str, str]]] = {
    "consumer": [("CPI", "month", "CPI 指数"), ("GDP", "quarter", "GDP")],
    "financial": [("GDP", "quarter", "GDP")],
    "industrial": [("GDP", "quarter", "GDP")],
    "default": [("CPI", "month", "CPI 指数")],
}

_COUNTRY_LABELS = {
    "china": "中国",
    "united_states": "美国",
    "united kingdom": "英国",
    "japan": "日本",
}

# FRED series for global macro overlay (requires FRED_API_KEY)
_DEFAULT_FRED_SERIES: tuple[tuple[str, str], ...] = (
    ("CPIAUCSL", "美国 CPI"),
    ("FEDFUNDS", "联邦基金利率"),
    ("DGS10", "美国 10Y 国债"),
    ("DEXCHUS", "美元/人民币汇率"),
)


def _sector_bucket(sector: str | None, industry: str | None) -> str:
    text = f"{sector or ''} {industry or ''}".lower()
    for key in (
        "consumer",
        "financial",
        "industrial",
        "technology",
        "energy",
        "healthcare",
        "real estate",
        "utility",
    ):
        if key.replace(" ", "") in text.replace(" ", "") or key in text:
            return "utilities" if key == "utility" else key
    return "default"


def _fmt_pct(v: float | None) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return f"{float(v):.2%}"


def _latest_series_summary(df: pd.DataFrame) -> dict[str, Any] | None:
    if df is None or df.empty:
        return None
    work = df.sort_index() if isinstance(df.index, pd.DatetimeIndex) else df
    if "date" in work.columns:
        work = work.sort_values("date")
    last = work.iloc[-1]
    prev = work.iloc[-2] if len(work) > 1 else None
    date_val = str(work.index[-1])[:10] if isinstance(work.index, pd.DatetimeIndex) else str(
        last.get("date", "")
    )[:10]
    value = float(last.get("value", last.iloc[-1]))
    change_pct: float | None = None
    if prev is not None:
        prev_v = float(prev.get("value", prev.iloc[-1]))
        if prev_v:
            change_pct = (value - prev_v) / abs(prev_v)
    return {
        "date": date_val,
        "value": value,
        "change_pct": change_pct,
    }


def fetch_country_macro_snapshot(country: str = "china") -> dict[str, Any]:
    """Latest macro snapshot via OpenBB econdb country_profile + key indicators."""
    if not openbb_available():
        return {"available": False, "country": country}

    from openbb import obb

    country_key = country.strip().lower().replace(" ", "_")
    label = _COUNTRY_LABELS.get(country_key, country)
    out: dict[str, Any] = {
        "available": True,
        "country": country_key,
        "label": label,
        "provider": "econdb",
    }

    try:
        prof_df = obb.economy.country_profile(country=country_key, provider="econdb").to_df()
        if not prof_df.empty:
            row = prof_df.iloc[0]
            out["profile"] = {
                k: (float(v) if isinstance(v, (int, float)) and not pd.isna(v) else v)
                for k, v in row.to_dict().items()
                if v is not None and not (isinstance(v, float) and pd.isna(v))
            }
    except Exception as e:
        logger.debug("country_profile %s: %s", country_key, e)
        out["profile_error"] = str(e)

    indicators: list[dict[str, Any]] = []
    for symbol, freq, name in (
        ("CPI", "month", "CPI"),
        ("GDP", "quarter", "GDP"),
    ):
        if country_key != "china":
            continue
        try:
            df = obb.economy.indicators(
                country=country_key,
                provider="econdb",
                symbol=symbol,
                frequency=freq,
            ).to_df()
            summary = _latest_series_summary(df)
            if summary:
                indicators.append({"name": name, "symbol": symbol, "frequency": freq, **summary})
        except Exception as e:
            logger.debug("indicator %s %s: %s", country_key, symbol, e)

    if indicators:
        out["indicators"] = indicators

    if country_key == "china":
        try:
            spi = obb.economy.share_price_index(country="china", provider="oecd").to_df()
            spi_sum = _latest_series_summary(spi)
            if spi_sum:
                out["equity_index"] = {"name": "OECD 股价指数", **spi_sum}
        except Exception as e:
            logger.debug("share_price_index china: %s", e)

    return out


def fetch_fred_series(
    *,
    start_date: str = "2020-01-01",
    series: tuple[tuple[str, str], ...] | None = None,
) -> list[dict[str, Any]]:
    """FRED time series when ``FRED_API_KEY`` is configured."""
    import os

    if not openbb_available() or not os.environ.get("FRED_API_KEY"):
        return []

    from openbb import obb

    rows: list[dict[str, Any]] = []
    for symbol, label in series or _DEFAULT_FRED_SERIES:
        try:
            df = obb.economy.fred_series(
                symbol=symbol,
                provider="fred",
                start_date=start_date,
            ).to_df()
            summary = _latest_series_summary(df)
            if summary:
                rows.append({"symbol": symbol, "label": label, "provider": "fred", **summary})
        except Exception as e:
            logger.debug("fred %s: %s", symbol, e)
            rows.append({"symbol": symbol, "label": label, "error": str(e)})
    return rows


def fetch_macro_context(
    *,
    countries: tuple[str, ...] = ("china", "united_states"),
    use_fred: bool = True,
    fred_start_date: str = "2020-01-01",
) -> dict[str, Any]:
    """Macro panel for report: China focus + optional global reference."""
    if not openbb_available():
        return {"available": False}

    from quant_rd_tool.openbb_settings import configure_openbb_credentials

    creds = configure_openbb_credentials()

    snapshots = []
    for c in countries:
        snap = fetch_country_macro_snapshot(c)
        if snap.get("available"):
            snapshots.append(snap)

    if not snapshots:
        return {"available": False, "reason": "no macro data returned"}

    china = next((s for s in snapshots if s.get("country") == "china"), snapshots[0])
    global_ref = [s for s in snapshots if s.get("country") != "china"]

    out: dict[str, Any] = {
        "available": True,
        "china": china,
        "global": global_ref,
        "summary": _build_macro_summary(china, global_ref),
        "credentials": creds,
    }

    if use_fred and creds.get("fred"):
        fred_rows = fetch_fred_series(start_date=fred_start_date)
        if fred_rows:
            out["fred"] = fred_rows

    return out


def _build_macro_summary(china: dict[str, Any], global_ref: list[dict[str, Any]]) -> str:
    prof = china.get("profile") or {}
    parts: list[str] = []
    if prof.get("gdp_yoy") is not None:
        parts.append(f"中国 GDP 同比约 {_fmt_pct(prof.get('gdp_yoy'))}")
    if prof.get("cpi_yoy") is not None:
        parts.append(f"CPI 同比 {_fmt_pct(prof.get('cpi_yoy'))}")
    if prof.get("policy_rate") is not None:
        parts.append(f"政策利率 {float(prof['policy_rate']):.2%}")
    for g in global_ref[:1]:
        gp = g.get("profile") or {}
        glabel = g.get("label", g.get("country", ""))
        if gp.get("gdp_yoy") is not None:
            parts.append(f"{glabel} GDP 同比 {_fmt_pct(gp.get('gdp_yoy'))}")
    if not parts:
        return "已连接 OpenBB，但宏观快照字段不完整（可配置 FRED/FMP 以扩展）。"
    return "；".join(parts) + "。"


def fetch_industry_context(
    symbol: str,
    *,
    profile: dict[str, Any] | None = None,
    use_fmp_peers: bool = True,
) -> dict[str, Any]:
    """Industry/sector context from equity profile + China macro linkage."""
    if not openbb_available():
        return {"available": False}

    from quant_rd_tool.openbb_data import fetch_equity_snapshot
    from quant_rd_tool.openbb_settings import configure_openbb_credentials

    configure_openbb_credentials()

    prof = profile or fetch_equity_snapshot(symbol)
    sector = (prof or {}).get("sector")
    industry = (prof or {}).get("industry")
    bucket = _sector_bucket(sector, industry)

    out: dict[str, Any] = {
        "available": True,
        "sector": sector,
        "industry": industry,
        "sector_bucket": bucket,
    }

    china_snap = fetch_country_macro_snapshot("china")
    prof_cn = china_snap.get("profile") or {}
    sector_metrics: list[dict[str, Any]] = []
    for key, label in _SECTOR_PROFILE_KEYS.get(bucket, _SECTOR_PROFILE_KEYS["default"]):
        if key in prof_cn:
            sector_metrics.append(
                {
                    "key": key,
                    "label": label,
                    "value": prof_cn[key],
                    "formatted": _fmt_pct(prof_cn[key])
                    if "yoy" in key or key.endswith("_rate")
                    else f"{float(prof_cn[key]):.4f}",
                }
            )
    if sector_metrics:
        out["sector_macro_metrics"] = sector_metrics

    from openbb import obb

    series_rows: list[dict[str, Any]] = []
    for symbol_code, freq, name in _SECTOR_ECONDB_SERIES.get(
        bucket, _SECTOR_ECONDB_SERIES["default"]
    ):
        try:
            df = obb.economy.indicators(
                country="china",
                provider="econdb",
                symbol=symbol_code,
                frequency=freq,
            ).to_df()
            summary = _latest_series_summary(df)
            if summary:
                series_rows.append({"name": name, "symbol": symbol_code, **summary})
        except Exception as e:
            logger.debug("sector series %s: %s", symbol_code, e)
    if series_rows:
        out["indicator_series"] = series_rows

    import os

    if use_fmp_peers and os.environ.get("FMP_API_KEY"):
        obb_sym = to_openbb_symbol(symbol)
        try:
            peers_df = obb.equity.compare.peers(symbol=obb_sym, provider="fmp").to_df()
            if peers_df is not None and not peers_df.empty:
                col = "symbol" if "symbol" in peers_df.columns else peers_df.columns[0]
                out["peers"] = peers_df[col].astype(str).tolist()[:8]
        except Exception as e:
            logger.debug("fmp peers: %s", e)

    out["interpretation"] = _build_industry_interpretation(out, prof)
    return out


def _build_industry_interpretation(
    ctx: dict[str, Any],
    profile: dict[str, Any] | None,
) -> str:
    name = (profile or {}).get("name") or ""
    sector = ctx.get("sector") or "未知板块"
    industry = ctx.get("industry") or "未知行业"
    metrics = ctx.get("sector_macro_metrics") or []
    macro_bits = [f"{m['label']}{m['formatted']}" for m in metrics[:3] if m.get("formatted")]
    macro_text = "、".join(macro_bits) if macro_bits else "暂无匹配的宏观同比指标"
    prefix = f"{name}（{sector} / {industry}）" if name else f"{sector} / {industry}"
    return f"{prefix}：与板块相关的中国宏观背景 — {macro_text}。"
