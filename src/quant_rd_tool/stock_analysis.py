"""Single-stock pipeline: fetch → local CSV/qlib → analysis report."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_rd_tool import akshare_data as ak_data
from quant_rd_tool import market_data as mkt
from quant_rd_tool.market_data import DataProvider
from quant_rd_tool.qlib_ml import MlAlgorithm, run_ml_analysis
from quant_rd_tool.stock_analyzer import analyze_ohlcv, build_narrative
from quant_rd_tool.stock_storage import (
    csv_path,
    load_csv,
    qlib_path,
    read_meta,
    report_json_path,
    report_md_path,
    save_csv,
    save_qlib,
    stock_root,
    write_meta,
)


def _render_markdown(report: dict[str, Any]) -> str:
    a = report["analysis"]
    n = report["narrative"]
    lines = [
        f"# 个股分析报告 — {a['symbol']}",
        "",
        f"**生成时间**：{report.get('generated_at', '')}",
        "",
        "## 摘要",
        "",
        n["summary"],
        "",
        f"**综合立场**：{n['stance']}",
        "",
        "## 价格与收益",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 最新收盘 | {a['price']['latest_close']} |",
        f"| 区间最高 | {a['price']['period_high']} |",
        f"| 区间最低 | {a['price']['period_low']} |",
        f"| 距高点 | {a['price']['pct_from_high']:.2%} |",
        f"| 近 5 日收益 | {_fmt_pct(a['returns'].get('5d'))} |",
        f"| 近 20 日收益 | {_fmt_pct(a['returns'].get('20d'))} |",
        f"| 近 60 日收益 | {_fmt_pct(a['returns'].get('60d'))} |",
        "",
        "## 风险指标（qlib）",
        "",
    ]
    risk = a.get("risk") or {}
    for k, label in (
        ("annualized_return", "年化收益"),
        ("annualized_volatility", "日收益标准差"),
        ("sharpe_ratio", "信息比率"),
        ("max_drawdown", "最大回撤"),
    ):
        v = risk.get(k)
        if k == "sharpe_ratio":
            text = "N/A" if v is None else f"{v:.4f}"
        elif k == "annualized_volatility":
            text = "N/A" if v is None else f"{v:.4f}"
        else:
            text = _fmt_pct(v)
        lines.append(f"- {label}：{text}")

    lines.extend(["", "## 技术面", ""])
    tech = a["technical"]
    lines.append(f"- 均线排列：{tech['ma_alignment']}")
    lines.append(f"- RSI(14)：{tech.get('rsi_14', 'N/A')}（{tech.get('rsi_zone', '')}）")
    if tech.get("close_vs_sma20") is not None:
        lines.append(f"- 收盘相对 MA20：{tech['close_vs_sma20']:.2%}")

    if a.get("benchmark"):
        lines.extend(["", "## 相对基准", ""])
        b = a["benchmark"]
        lines.append(f"- 基准：{b.get('benchmark_code')}")
        lines.append(f"- 相关系数：{b.get('correlation')}")
        lines.append(f"- Beta：{b.get('beta')}")

    ml = report.get("ml_analysis")
    if ml and (ml.get("enabled") or ml.get("models")):
        lines.extend(["", "## 机器学习（qlib Alpha158 + XGBoost / LightGBM）", ""])
        if ml.get("algorithm") == "both" and ml.get("models"):
            comp = ml.get("comparison") or {}
            if comp.get("summary"):
                lines.append(comp["summary"])
                lines.append("")
            for algo, m in (ml.get("models") or {}).items():
                if not m.get("enabled"):
                    continue
                lines.extend(_ml_section_lines(m, title=f"### {algo.upper()}"))
        else:
            lines.extend(_ml_section_lines(ml))
    elif ml and ml.get("skipped"):
        lines.extend(["", "## 机器学习", "", f"_{ml.get('reason', '已跳过')}_", ""])

    obb = report.get("openbb")
    if obb and obb.get("available"):
        profile = obb.get("profile") or {}
        if profile:
            lines.extend(["", "## OpenBB 公司概况", ""])
            for key, label in (
                ("name", "名称"),
                ("sector", "板块"),
                ("industry", "行业"),
                ("market_cap", "市值"),
            ):
                if profile.get(key) is not None:
                    lines.append(f"- {label}：{profile[key]}")
        news = obb.get("news") or []
        if news:
            lines.extend(["", "## OpenBB 相关新闻", ""])
            for item in news[:5]:
                title = item.get("title", "")
                lines.append(f"- {title}")

        macro = obb.get("macro") or {}
        if macro.get("available"):
            lines.extend(["", "## 宏观环境（OpenBB）", ""])
            if macro.get("summary"):
                lines.append(macro["summary"])
                lines.append("")
            china = macro.get("china") or {}
            prof = china.get("profile") or {}
            macro_rows = (
                ("gdp_yoy", "GDP 同比"),
                ("cpi_yoy", "CPI 同比"),
                ("industrial_production_yoy", "工业增加值同比"),
                ("retail_sales_yoy", "社会零售同比"),
                ("policy_rate", "政策利率"),
                ("yield_10y", "10Y 国债"),
                ("jobless_rate", "失业率"),
            )
            for key, label in macro_rows:
                if prof.get(key) is not None:
                    val = prof[key]
                    text = _fmt_pct(val) if "yoy" in key or key.endswith("_rate") else f"{float(val):.4f}"
                    lines.append(f"- {label}：{text}")
            for ind in china.get("indicators") or []:
                chg = ind.get("change_pct")
                chg_s = f"，环比 {chg:.2%}" if chg is not None else ""
                lines.append(
                    f"- {ind.get('name')}（{ind.get('date')}）：{ind.get('value')}{chg_s}"
                )
            idx = china.get("equity_index")
            if idx:
                lines.append(
                    f"- 市场指数 {idx.get('name')}（{idx.get('date')}）：{idx.get('value')}"
                )
            for g in macro.get("global") or []:
                gp = g.get("profile") or {}
                glabel = g.get("label", g.get("country", ""))
                if gp.get("gdp_yoy") is not None or gp.get("cpi_yoy") is not None:
                    lines.append(
                        f"- {glabel}：GDP 同比 {_fmt_pct(gp.get('gdp_yoy'))}，"
                        f"CPI 同比 {_fmt_pct(gp.get('cpi_yoy'))}"
                    )
            for row in macro.get("fred") or []:
                if row.get("error"):
                    continue
                chg = row.get("change_pct")
                chg_s = f"，环比 {chg:.2%}" if chg is not None else ""
                lines.append(
                    f"- FRED {row.get('label')}（{row.get('date')}）："
                    f"{row.get('value')}{chg_s}"
                )

        industry = obb.get("industry") or {}
        if industry.get("available"):
            lines.extend(["", "## 行业背景（OpenBB）", ""])
            if industry.get("interpretation"):
                lines.append(industry["interpretation"])
                lines.append("")
            if industry.get("sector"):
                lines.append(f"- 板块：{industry['sector']}")
            if industry.get("industry"):
                lines.append(f"- 细分行业：{industry['industry']}")
            for m in industry.get("sector_macro_metrics") or []:
                lines.append(f"- {m.get('label')}：{m.get('formatted')}")
            for s in industry.get("indicator_series") or []:
                lines.append(
                    f"- {s.get('name')}（{s.get('date')}）：{s.get('value')}"
                )
            peers = industry.get("peers")
            if peers:
                lines.append(f"- 同业（FMP）：{', '.join(peers[:6])}")

        if obb.get("summary"):
            lines.extend(["", "## OpenBB 研究摘要", "", obb["summary"], ""])

        fund = obb.get("fundamentals") or {}
        metrics = fund.get("metrics") if isinstance(fund.get("metrics"), dict) else {}
        ratios = fund.get("ratios") if isinstance(fund.get("ratios"), dict) else {}
        if metrics or ratios:
            lines.extend(["", "## 基本面（OpenBB）", ""])
            for block in (ratios, metrics):
                for k, v in list(block.items())[:8]:
                    lines.append(f"- {k}：{v}")

        est = obb.get("estimates") or {}
        if est:
            lines.extend(["", "## 盈利预期（OpenBB）", ""])
            for k, v in est.items():
                if isinstance(v, dict):
                    lines.append(f"- {k}：{', '.join(f'{a}={b}' for a, b in list(v.items())[:5])}")

        cal = obb.get("calendar") or {}
        if cal:
            lines.extend(["", "## 事件日历（OpenBB）", ""])
            for k, rows in cal.items():
                if isinstance(rows, list) and rows:
                    lines.append(f"- {k}：{len(rows)} 条")

        tech_ob = obb.get("technical_overlay")
        if tech_ob:
            lines.extend(["", "## 扩展技术面（OpenBB 本地叠加）", ""])
            macd = tech_ob.get("macd") or {}
            lines.append(f"- MACD：{macd.get('trend', 'N/A')}")
            bb = tech_ob.get("bollinger") or {}
            lines.append(f"- 布林带：{bb.get('zone', 'N/A')}")
            if tech_ob.get("atr14") is not None:
                lines.append(f"- ATR(14)：{tech_ob['atr14']:.4f}")

        events = obb.get("economy_events") or []
        if events:
            lines.extend(["", "## 宏观事件日历", ""])
            for ev in events[:5]:
                title = ev.get("event") or ev.get("title") or str(ev)[:60]
                lines.append(f"- {title}")

        fx = (obb.get("cross_asset") or {}).get("fx_usdcny")
        if fx and fx.get("rate") is not None:
            lines.append(f"- USD/CNY：{fx['rate']}")

    lines.extend(["", "## 观察要点", ""])
    for obs in n["observations"]:
        lines.append(f"- {obs}")

    lines.extend(["", "## 风险提示", ""])
    for r in n["risks"]:
        lines.append(f"- {r}")

    lines.extend(["", "---", "", n["disclaimer"]])
    return "\n".join(lines) + "\n"


def _ml_section_lines(ml: dict[str, Any], *, title: str = "") -> list[str]:
    lines: list[str] = []
    if title:
        lines.append(title)
    interp = ml.get("interpretation") or {}
    if interp.get("summary"):
        lines.append(interp["summary"])
    lines.append(f"- **模型信号**：{ml.get('latest', {}).get('signal', 'N/A')}")
    tm = ml.get("test_metrics") or {}
    if tm.get("ic") is not None:
        lines.append(f"- 测试集 IC：{tm['ic']:.4f}")
    if tm.get("direction_accuracy") is not None:
        lines.append(f"- 测试集方向命中率：{tm['direction_accuracy']:.2%}")
    latest = ml.get("latest") or {}
    if latest.get("predicted_return") is not None:
        lines.append(f"- 最新预测收益（标签代理）：{latest['predicted_return']:.4f}")
    lines.append("")
    lines.append("**重要因子（Top 5）**")
    for row in (ml.get("top_features") or [])[:5]:
        lines.append(f"- {row['feature']}: {row['importance']}")
    for c in interp.get("caveats") or []:
        lines.append(f"- _{c}_")
    lines.append("")
    return lines


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v:.2%}"


def analyze_stock(
    symbol: str,
    *,
    start_date: str = "2020-01-01",
    end_date: str | None = None,
    data_dir: str | Path = "data/stocks",
    refresh: bool = False,
    with_benchmark: bool = True,
    benchmark: str = "sh000300",
    with_ml: bool = True,
    ml_algorithm: MlAlgorithm = "both",
    data_provider: DataProvider = "auto",
    with_openbb_enrichment: bool = True,
) -> dict[str, Any]:
    """
    Fetch (or load) one stock, persist CSV + qlib bins, run analysis, write reports.

    Local layout::

        {data_dir}/{SH600519}/
            ohlcv.csv
            qlib/          # calendars, instruments, features
            meta.json
            report.json
            report.md
    """
    if end_date is None:
        end_date = date.today().isoformat()

    qlib_code = ak_data.to_qlib_code(symbol)
    root = stock_root(data_dir, symbol)
    csv_file = csv_path(root)
    qlib_dir = qlib_path(root)

    fetched = False
    if refresh or not csv_file.exists():
        df = mkt.fetch_stock_daily(
            symbol,
            start_date=start_date,
            end_date=end_date,
            provider=data_provider,
        )
        source = data_provider if data_provider != "auto" else "auto(akshare→openbb)"
        save_csv(df, csv_file)
        save_qlib(df, qlib_dir)
        write_meta(
            root,
            {
                "symbol": qlib_code,
                "start_date": start_date,
                "end_date": end_date,
                "source": source,
                "adjust": "qfq" if data_provider != "openbb" else "provider-dependent",
            },
        )
        fetched = True
    else:
        df = load_csv(csv_file)
        if not qlib_dir.exists():
            save_qlib(df, qlib_dir)

    bench_df: pd.DataFrame | None = None
    if with_benchmark:
        try:
            bench_df = ak_data.fetch_index_daily(
                benchmark,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            bench_df = None

    analysis = analyze_ohlcv(df, benchmark_df=bench_df)
    narrative = build_narrative(analysis)

    ml_analysis: dict[str, Any] | None = None
    if with_ml:
        try:
            ml_analysis = run_ml_analysis(
                str(qlib_dir.resolve()),
                qlib_code,
                start_date=start_date,
                end_date=end_date,
                num_bars=len(df),
                algorithm=ml_algorithm,
            )
        except Exception as e:
            ml_analysis = {"enabled": False, "skipped": True, "reason": str(e)}

    openbb_context: dict[str, Any] | None = None
    if with_openbb_enrichment:
        try:
            openbb_context = mkt.enrich_with_openbb(symbol, ohlcv=df)
        except Exception as e:
            openbb_context = {"available": False, "error": str(e)}

    report: dict[str, Any] = {
        "symbol": qlib_code,
        "data_paths": {
            "root": str(root.resolve()),
            "csv": str(csv_file.resolve()),
            "qlib": str(qlib_dir.resolve()),
        },
        "fetched_new_data": fetched,
        "meta": read_meta(root),
        "analysis": analysis,
        "narrative": narrative,
        "ml_analysis": ml_analysis,
        "openbb": openbb_context,
        "generated_at": now_iso(),
    }
    report["markdown"] = _render_markdown(report)

    from quant_rd_tool.report_versions import archive_report_if_exists
    from quant_rd_tool.research_audit import hash_payload, record_research_run

    archive_report_if_exists(root)

    report_body = {k: v for k, v in report.items() if k != "markdown"}
    content_hash = hash_payload(report_body)
    compliance = record_research_run(
        "analyze_stock",
        code=ak_data.to_ak_code(symbol),
        inputs={
            "start_date": start_date,
            "end_date": end_date,
            "with_ml": with_ml,
            "ml_algorithm": ml_algorithm,
            "data_provider": data_provider,
        },
        outputs_summary={
            "stance": narrative.get("stance"),
            "content_hash": content_hash,
            "qlib_code": qlib_code,
        },
        data_dir=data_dir,
    )
    report_body["_compliance"] = compliance

    report_json_path(root).write_text(
        json.dumps(report_body, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_md_path(root).write_text(report["markdown"], encoding="utf-8")

    report["_compliance"] = compliance
    return report
