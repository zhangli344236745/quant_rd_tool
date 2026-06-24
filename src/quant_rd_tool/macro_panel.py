"""Standalone OpenBB macro / industry panel (CLI & API)."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool.openbb_data import openbb_available
from quant_rd_tool.openbb_research import build_openbb_research


def build_macro_panel(
    *,
    code: str | None = None,
    countries: tuple[str, ...] = ("china", "united_states"),
    use_fred: bool = True,
    fred_start_date: str = "2020-01-01",
    use_fmp_peers: bool = True,
) -> dict[str, Any]:
    """Assemble macro (+ optional per-stock industry) panel."""
    if not openbb_available():
        msg = "OpenBB 未安装。请运行: uv sync"
        raise ImportError(msg)

    if code:
        research = build_openbb_research(
            code,
            include_macro=True,
            use_fred=use_fred,
            macro_countries=countries,
        )
        if not use_fmp_peers and research.get("industry"):
            research["industry"].pop("peers", None)
    else:
        from quant_rd_tool.openbb_equity import fetch_economy_calendar_events
        from quant_rd_tool.openbb_macro import fetch_macro_context
        from quant_rd_tool.openbb_settings import configure_openbb_credentials

        configure_openbb_credentials()
        research = {
            "available": True,
            "symbol": None,
            "macro": fetch_macro_context(countries=countries, use_fred=use_fred),
            "economy_events": fetch_economy_calendar_events(),
        }

    panel: dict[str, Any] = {
        "generated_at": now_iso(),
        "openbb": research,
        "macro": research.get("macro"),
        "industry": research.get("industry") if code else None,
        "symbol": code,
    }

    panel["markdown"] = render_macro_markdown(panel)
    return panel


def render_macro_markdown(panel: dict[str, Any]) -> str:
    lines = ["# 宏观 / 行业面板（OpenBB）", "", f"**生成时间**：{panel.get('generated_at', '')}", ""]

    macro = panel.get("macro") or {}
    if not macro.get("available"):
        lines.append("_宏观数据不可用。_")
    else:
        lines.extend(["## 宏观摘要", "", macro.get("summary", ""), ""])
        china = macro.get("china") or {}
        prof = china.get("profile") or {}
        if prof:
            lines.extend(["## 中国宏观（econdb）", ""])
            rows = (
                ("gdp_yoy", "GDP 同比"),
                ("cpi_yoy", "CPI 同比"),
                ("industrial_production_yoy", "工业增加值同比"),
                ("retail_sales_yoy", "社会零售同比"),
                ("policy_rate", "政策利率"),
                ("yield_10y", "10Y 国债"),
                ("jobless_rate", "失业率"),
            )
            for key, label in rows:
                if prof.get(key) is not None:
                    v = prof[key]
                    if "yoy" in key or key.endswith("_rate"):
                        lines.append(f"- {label}：{float(v):.2%}")
                    else:
                        lines.append(f"- {label}：{float(v):.4f}")

        for g in macro.get("global") or []:
            gp = g.get("profile") or {}
            glabel = g.get("label", g.get("country", ""))
            lines.extend(["", f"## {glabel}宏观（econdb）", ""])
            if gp.get("gdp_yoy") is not None:
                lines.append(f"- GDP 同比：{float(gp['gdp_yoy']):.2%}")
            if gp.get("cpi_yoy") is not None:
                lines.append(f"- CPI 同比：{float(gp['cpi_yoy']):.2%}")

        fred = macro.get("fred") or []
        if fred:
            lines.extend(["", "## FRED 序列", ""])
            for row in fred:
                if row.get("error"):
                    lines.append(f"- {row.get('label')}：_{row['error'][:80]}_")
                    continue
                chg = row.get("change_pct")
                chg_s = f"，环比 {chg:.2%}" if chg is not None else ""
                lines.append(
                    f"- {row.get('label')}（{row.get('date')}）：{row.get('value')}{chg_s}"
                )

        creds = macro.get("credentials") or {}
        lines.extend(
            [
                "",
                "## 数据源凭证",
                "",
                f"- FRED：{'已配置' if creds.get('fred') else '未配置（设置 FRED_API_KEY）'}",
                f"- FMP：{'已配置' if creds.get('fmp') else '未配置（设置 FMP_API_KEY，用于同业）'}",
                "",
            ]
        )

    industry = panel.get("industry")
    if industry:
        lines.extend(["## 行业背景", ""])
        if industry.get("interpretation"):
            lines.append(industry["interpretation"])
            lines.append("")
        for m in industry.get("sector_macro_metrics") or []:
            lines.append(f"- {m.get('label')}：{m.get('formatted')}")
        if industry.get("peers"):
            lines.append(f"- 同业（FMP）：{', '.join(industry['peers'][:8])}")

    lines.append("---")
    lines.append("")
    lines.append("_研究用途，不构成投资建议。_")
    return "\n".join(lines) + "\n"


def save_macro_panel(panel: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    """Write panel.json and panel.md under output_dir."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "panel.json"
    md_path = root / "panel.md"
    payload = {k: v for k, v in panel.items() if k != "markdown"}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(panel.get("markdown", render_macro_markdown(panel)), encoding="utf-8")
    return {"json": str(json_path.resolve()), "markdown": str(md_path.resolve())}
