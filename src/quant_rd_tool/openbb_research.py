"""Unified OpenBB research bundle for analyze / CLI / API."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_rd_tool.openbb_capabilities import list_capabilities, probe_capabilities
from quant_rd_tool.openbb_data import fetch_company_news, fetch_equity_snapshot, openbb_available
from quant_rd_tool.openbb_equity import (
    compute_technical_overlay,
    fetch_cross_asset_fx,
    fetch_economy_calendar_events,
    fetch_equity_calendar,
    fetch_estimates,
    fetch_fundamentals,
)
from quant_rd_tool.openbb_macro import fetch_industry_context, fetch_macro_context
from quant_rd_tool.openbb_settings import configure_openbb_credentials


def build_openbb_research(
    symbol: str,
    *,
    ohlcv: pd.DataFrame | None = None,
    include_macro: bool = True,
    use_fred: bool = True,
    macro_countries: tuple[str, ...] = ("china", "united_states"),
) -> dict[str, Any]:
    """
    Aggregate OpenBB modules wired into quant-rd-tool.

    Always attempts econdb macro; FMP/FRED/yfinance paths are best-effort.
    """
    if not openbb_available():
        return {"available": False, "reason": "openbb not installed"}

    creds = configure_openbb_credentials()
    profile = fetch_equity_snapshot(symbol)

    research: dict[str, Any] = {
        "available": True,
        "symbol": symbol,
        "credentials": creds,
        "capabilities": probe_capabilities(),
        "profile": profile,
        "news": fetch_company_news(symbol),
        "fundamentals": fetch_fundamentals(symbol),
        "estimates": fetch_estimates(symbol),
        "calendar": fetch_equity_calendar(symbol),
        "economy_events": fetch_economy_calendar_events(),
        "cross_asset": {"fx_usdcny": fetch_cross_asset_fx()},
    }

    if include_macro:
        research["macro"] = fetch_macro_context(
            countries=macro_countries,
            use_fred=use_fred,
        )
        research["industry"] = fetch_industry_context(symbol, profile=profile)

    if ohlcv is not None and not ohlcv.empty:
        research["technical_overlay"] = compute_technical_overlay(ohlcv)

    research["summary"] = _build_research_summary(research)
    return research


def _build_research_summary(data: dict[str, Any]) -> str:
    parts: list[str] = []
    macro = data.get("macro") or {}
    if macro.get("summary"):
        parts.append(macro["summary"].rstrip("。"))

    fund = data.get("fundamentals") or {}
    metrics = fund.get("metrics") if isinstance(fund.get("metrics"), dict) else {}
    for key, label in (("pe_ratio", "PE"), ("price_to_book", "PB"), ("return_on_equity", "ROE")):
        if metrics.get(key) is not None:
            parts.append(f"{label} {metrics[key]}")

    tech = data.get("technical_overlay") or {}
    macd = tech.get("macd") or {}
    if macd.get("trend"):
        parts.append(f"技术 {macd['trend']}")

    if not parts:
        return "OpenBB 研究包已加载；配置 FMP/FRED Key 可解锁估值与宏观日历。"
    return "；".join(parts) + "。"


def render_openbb_markdown(data: dict[str, Any]) -> str:
    """Markdown section(s) for reports."""
    if not data.get("available"):
        return "_OpenBB 不可用_\n"

    lines = ["## OpenBB 研究摘要", "", data.get("summary", ""), ""]

    profile = data.get("profile") or {}
    if profile:
        lines.extend(["### 公司概况", ""])
        for key, label in (
            ("name", "名称"),
            ("sector", "板块"),
            ("industry", "行业"),
            ("market_cap", "市值"),
        ):
            if profile.get(key) is not None:
                lines.append(f"- {label}：{profile[key]}")
        lines.append("")

    fund = data.get("fundamentals") or {}
    ratios = fund.get("ratios")
    metrics = fund.get("metrics")
    if ratios or metrics:
        lines.extend(["### 基本面（OpenBB）", ""])
        for block in (ratios, metrics):
            if isinstance(block, dict):
                for k, v in list(block.items())[:10]:
                    lines.append(f"- {k}：{v}")
        lines.append("")

    est = data.get("estimates") or {}
    if est:
        lines.extend(["### 盈利预期（OpenBB / FMP）", ""])
        for k, v in est.items():
            if isinstance(v, dict):
                lines.append(f"- {k}：{', '.join(f'{a}={b}' for a, b in list(v.items())[:6])}")
            elif isinstance(v, list) and v:
                lines.append(f"- {k}：{len(v)} 条记录")
        lines.append("")

    cal = data.get("calendar") or {}
    if cal:
        lines.extend(["### 公司事件日历", ""])
        for k, rows in cal.items():
            if isinstance(rows, list):
                lines.append(f"- {k}：{len(rows)} 条")
        lines.append("")

    tech = data.get("technical_overlay")
    if tech:
        lines.extend(["### 扩展技术面（MACD / 布林 / ATR）", ""])
        macd = tech.get("macd") or {}
        lines.append(f"- MACD：{macd.get('trend', 'N/A')}（柱 {macd.get('histogram', 'N/A')}）")
        bb = tech.get("bollinger") or {}
        lines.append(f"- 布林带：{bb.get('zone', 'N/A')}")
        if tech.get("atr14") is not None:
            lines.append(f"- ATR(14)：{tech['atr14']:.4f}")
        lines.append("")

    events = data.get("economy_events") or []
    if events:
        lines.extend(["### 宏观事件日历", ""])
        for ev in events[:5]:
            title = ev.get("event") or ev.get("title") or ev.get("name") or str(ev)[:80]
            lines.append(f"- {title}")
        lines.append("")

    fx = (data.get("cross_asset") or {}).get("fx_usdcny")
    if fx:
        chg = fx.get("change_pct")
        chg_s = f"，日变 {chg:.2%}" if chg is not None else ""
        lines.append(f"### 汇率\n\n- USD/CNY：{fx.get('rate')}{chg_s}\n")

    creds = data.get("credentials") or {}
    lines.append(
        f"_凭证：FRED={'✓' if creds.get('fred') else '×'} "
        f"FMP={'✓' if creds.get('fmp') else '×'}_\n"
    )
    return "\n".join(lines)


def get_capabilities_report(*, probe: bool = True) -> dict[str, Any]:
    return probe_capabilities() if probe else list_capabilities()
