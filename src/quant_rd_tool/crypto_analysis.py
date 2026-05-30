"""Crypto analyze pipeline: ccxt OHLCV → qlib → ML → report."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analyzer import (
    analyze_crypto_ohlcv,
    build_crypto_narrative,
    derive_trading_signal,
)
from quant_rd_tool.crypto_ml import (
    merge_crypto_signals,
    ml_markdown_lines,
    run_crypto_ml_analysis,
)
from quant_rd_tool.crypto_time import utc_now_beijing_str
from quant_rd_tool.qlib_dump import QlibDataDumper
from quant_rd_tool.qlib_ml import MlAlgorithm


def crypto_root(data_dir: str | Path, symbol: str) -> Path:
    code = cxt.to_qlib_code(symbol)
    return Path(data_dir) / code


def format_period_bounds(df: pd.DataFrame, timeframe: str) -> tuple[str, str]:
    start_ts = pd.Timestamp(df["date"].min())
    end_ts = pd.Timestamp(df["date"].max())
    if timeframe in ("1d", "1D", "day"):
        return str(start_ts.date()), str(end_ts.date())
    return start_ts.strftime("%Y-%m-%d %H:%M:%S"), end_ts.strftime("%Y-%m-%d %H:%M:%S")


def analyze_crypto_from_df(
    df: pd.DataFrame,
    symbol: str,
    *,
    data_dir: str | Path = "data/crypto",
    timeframe: str = "1d",
    with_qlib: bool = True,
    with_ml: bool = True,
    ml_algorithm: MlAlgorithm = "both",
) -> dict[str, Any]:
    """Run technical + optional qlib ML analysis on an in-memory OHLCV frame."""
    root = crypto_root(data_dir, symbol)
    root.mkdir(parents=True, exist_ok=True)

    from quant_rd_tool.crypto_storage import ohlcv_csv_path, qlib_dir_for

    csv_file = ohlcv_csv_path(root, timeframe)
    qlib_dir = qlib_dir_for(root, timeframe)
    qlib_code = cxt.to_qlib_code(symbol)
    qlib_freq = cxt.timeframe_to_qlib_freq(timeframe)

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work.to_csv(csv_file, index=False)

    start_date, end_date = format_period_bounds(work, timeframe)

    if with_qlib:
        QlibDataDumper(qlib_dir, freq=qlib_freq).dump({qlib_code: work})

    analysis = analyze_crypto_ohlcv(work)
    technical_signal = derive_trading_signal(analysis)

    ml_analysis: dict[str, Any] | None = None
    if with_ml and with_qlib:
        try:
            ml_analysis = run_crypto_ml_analysis(
                str(qlib_dir.resolve()),
                qlib_code,
                start_date=start_date,
                end_date=end_date,
                num_bars=len(work),
                algorithm=ml_algorithm,
                timeframe=timeframe,
            )
        except Exception as e:
            ml_analysis = {"enabled": False, "skipped": True, "reason": str(e)}

    combined = merge_crypto_signals(technical_signal, ml_analysis)
    narrative = build_crypto_narrative(
        analysis,
        technical_signal,
        combined_signal=combined,
        ml_analysis=ml_analysis,
        pair=cxt.to_ccxt_symbol(symbol),
        timeframe=timeframe,
    )
    narrative["agreement"] = combined.get("agreement")
    if combined.get("ml", {}).get("signal"):
        narrative["summary"] += f" 技术面与 ML {combined['agreement']}。"

    report: dict[str, Any] = {
        "symbol": analysis["symbol"],
        "pair": cxt.to_ccxt_symbol(symbol),
        "timeframe": timeframe,
        "period": {"start": start_date, "end": end_date, "bars": len(work)},
        "data_paths": {
            "root": str(root.resolve()),
            "csv": str(csv_file.resolve()),
            "qlib": str(qlib_dir.resolve()) if with_qlib else None,
        },
        "analysis": analysis,
        "technical_signal": technical_signal,
        "ml_analysis": ml_analysis,
        "combined_signal": combined,
        "signal": combined,
        "narrative": narrative,
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_at_beijing": utc_now_beijing_str(),
    }
    report["markdown"] = _render_markdown(report)

    (root / "report.json").write_text(
        json.dumps({k: v for k, v in report.items() if k != "markdown"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "report.md").write_text(report["markdown"], encoding="utf-8")
    return report


def analyze_crypto(
    symbol: str,
    *,
    data_dir: str | Path = "data/crypto",
    timeframe: str = "1d",
    limit: int = 500,
    refresh: bool = True,
    with_qlib: bool = True,
    with_ml: bool = True,
    ml_algorithm: MlAlgorithm = "both",
    exchange_id: cxt.ExchangeId = "binance",
) -> dict[str, Any]:
    """
    Fetch OHLCV → qlib bin → technical + qlib Alpha158 ML → combined 看涨/看跌 report.

    ML 需要日线且样本 ≥ 约 400 根；请使用 ``--timeframe 1d --limit 500``。
    """
    from quant_rd_tool.crypto_storage import ohlcv_csv_path

    root = crypto_root(data_dir, symbol)
    root.mkdir(parents=True, exist_ok=True)
    csv_file = ohlcv_csv_path(root, timeframe)

    if refresh or not csv_file.exists():
        df = cxt.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            limit=limit,
            exchange_id=exchange_id,
        )
    else:
        df = pd.read_csv(csv_file)
        df["date"] = pd.to_datetime(df["date"])

    return analyze_crypto_from_df(
        df,
        symbol,
        data_dir=data_dir,
        timeframe=timeframe,
        with_qlib=with_qlib,
        with_ml=with_ml,
        ml_algorithm=ml_algorithm,
    )


def _render_markdown(report: dict[str, Any]) -> str:
    a = report["analysis"]
    n = report["narrative"]
    s = report["combined_signal"]
    tf = report.get("timeframe", "1d")
    bar_label = "根 K 线" if tf != "1d" else "根日线"
    ret_label = "近 5/20 根" if tf != "1d" else "近 5/20 日"
    lines = [
        f"# 加密货币分析报告 — {report['pair']}",
        "",
        f"**周期**：{tf}",
        f"**生成时间**：{report.get('generated_at', '')}",
        f"**样本（北京时间）**：{report.get('period', {}).get('start')} ~ {report.get('period', {}).get('end')}"
        f"（{report.get('period', {}).get('bars')} {bar_label}）",
        "",
        "_说明：`ohlcv_*.csv` 的 `date` 列为 **北京时间 (UTC+8)**；`timestamp` 为 UTC 毫秒。"
        "最后一根可能为**未收盘**的当前 5m 柱。_",
        "",
        "## 综合研判（技术面 + qlib ML）",
        "",
        f"- **方向**：{s['stance']}（{s['action']}）",
        f"- **置信度**：{s['confidence']:.0%}",
        f"- **技术面 / ML**：{s.get('technical', {}).get('stance')} / "
        f"{s.get('ml', {}).get('stance') or 'N/A'}（{s.get('agreement', '')}）",
        "",
        n["summary"],
        "",
    ]

    brief = n.get("investment_brief") or {}
    if brief.get("markdown"):
        lines.append(brief["markdown"])
        lines.append("")

    ml = report.get("ml_analysis")
    if ml:
        lines.extend(["## 机器学习（qlib Alpha158 + XGBoost / LightGBM）", ""])
        lines.extend(ml_markdown_lines(ml))

    lines.extend(
        [
            "## 价格与收益",
            "",
            f"- 最新价：{a['price']['latest_close']}",
            f"- 区间高/低：{a['price']['period_high']} / {a['price']['period_low']}",
            f"- {ret_label}：{a['returns'].get('5d')} / {a['returns'].get('20d')}",
            "",
            "## 技术面",
            "",
            f"- 均线：{a['technical']['ma_alignment']}",
            f"- RSI：{a['technical'].get('rsi_14')}（{a['technical'].get('rsi_zone')}）",
            f"- MACD：{a['technical'].get('macd_trend', 'N/A')}",
            f"- 布林带：{a['technical'].get('bollinger_zone', 'N/A')}",
            "",
            "## 操作建议",
            "",
            n["advice"],
            "",
            "## 信号依据",
            "",
        ]
    )
    for r in s.get("reasons") or n.get("observations") or []:
        lines.append(f"- {r}")
    lines.extend(["", "## 风险提示", ""])
    for r in n["risks"]:
        lines.append(f"- {r}")
    lines.extend(["", "---", "", n["disclaimer"]])
    return "\n".join(lines) + "\n"
