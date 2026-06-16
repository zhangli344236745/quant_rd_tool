"""Configurable A-share analysis workflow: technical + qlib + strategy + VaR → advice."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

import pandas as pd

from quant_rd_tool.crypto_analysis import format_period_bounds
from quant_rd_tool.crypto_time import utc_now_beijing_str
from quant_rd_tool.crypto_var import parse_confidence_levels
from quant_rd_tool.crypto_workflow_price_levels import compute_iv_price_guidance
from quant_rd_tool.openbb_equity import compute_technical_overlay
from quant_rd_tool.oos_protocol import compact_oos_for_ui
from quant_rd_tool.qlib_dump import QlibDataDumper
from quant_rd_tool.qlib_ml import MlAlgorithm, run_ml_analysis
from quant_rd_tool.stock_analyzer import analyze_ohlcv, build_narrative
from quant_rd_tool.stock_codes import to_ak_code, to_qlib_code
from quant_rd_tool.stock_storage import qlib_path, stock_root
from quant_rd_tool.stock_var import build_symbol_var_report_from_df, fetch_ohlcv_df
from quant_rd_tool.stock_workflow_storage import save_run
from quant_rd_tool.stock_zipline_runner import run_pandas_backtest

StockStance = str  # 偏多 | 谨慎 | 中性

STEP_CATALOG: list[dict[str, Any]] = [
    {
        "id": "technical",
        "name": "技术面分析",
        "description": "均线、RSI、收益与风险等综合技术信号",
        "params_schema": {},
    },
    {
        "id": "announcement_scan",
        "name": "公告扫描",
        "description": "拉取近期公告并按关键词规则打分，识别高影响事件",
        "params_schema": {
            "min_score": {"type": "integer", "default": 40},
            "notice_limit": {"type": "integer", "default": 15},
            "refresh": {"type": "boolean", "default": True},
            "persist": {"type": "boolean", "default": True},
            "high_impact_min": {"type": "integer", "default": 70},
        },
    },
    {
        "id": "qlib_ml",
        "name": "qlib ML",
        "description": "Alpha158 + XGBoost / LightGBM 方向预测",
        "params_schema": {
            "algorithm": {"type": "string", "enum": ["xgb", "lgb", "both"], "default": "both"},
            "use_cache": {"type": "boolean", "default": True},
        },
    },
    {
        "id": "zipline_strategy",
        "name": "策略信号",
        "description": "Zipline 策略库末 bar 目标仓位（pandas 快算）",
        "params_schema": {
            "strategy_id": {"type": "string", "default": "ma_crossover"},
            "strategy_params": {"type": "object", "default": {}},
            "capital_base": {"type": "number", "default": 100_000},
        },
    },
    {
        "id": "var_symbol",
        "name": "单标的 VaR",
        "description": "历史模拟 VaR / CVaR 与回测违规率",
        "params_schema": {
            "notional_cny": {"type": "number", "default": 100_000},
            "lookback_bars": {"type": "integer", "default": 252},
            "horizon_days": {"type": "integer", "default": 1},
            "confidence": {"type": "string", "default": "0.95,0.99"},
            "mc_n_sims": {"type": "integer", "default": 3000},
        },
    },
    {
        "id": "advice_synth",
        "name": "投资建议合成",
        "description": "汇总各步产出综合研判与仓位建议",
        "params_schema": {
            "var_gate_pct": {"type": "number", "default": 0.08},
            "max_position_pct": {"type": "number", "default": 0.5},
            "horizon_days": {"type": "number", "default": None},
            "sl_sigma": {"type": "number", "default": 1.0},
            "tp_sigma": {"type": "number", "default": 1.5},
            "entry_sigma": {"type": "number", "default": 0.35},
        },
        "required": True,
    },
]

VALID_STEP_IDS = {s["id"] for s in STEP_CATALOG}
ADVICE_STEP = "advice_synth"


def list_step_catalog() -> list[dict[str, Any]]:
    return [dict(s) for s in STEP_CATALOG]


def normalize_template_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(steps):
        sid = str(raw.get("id") or "").strip()
        if sid not in VALID_STEP_IDS:
            continue
        out.append(
            {
                "id": sid,
                "enabled": raw.get("enabled", True) is not False,
                "order": int(raw.get("order", i)),
                "params": dict(raw.get("params") or {}),
            }
        )
    out.sort(key=lambda x: x["order"])
    if not any(s["id"] == ADVICE_STEP for s in out):
        out.append({"id": ADVICE_STEP, "enabled": True, "order": 999, "params": {}})
    return out


def _load_ohlcv(
    symbol: str,
    *,
    data_dir: str,
    timeframe: str,
    limit: int = 800,
    refresh: bool = True,
) -> pd.DataFrame:
    code = to_ak_code(symbol)
    df = fetch_ohlcv_df(code, data_dir=data_dir, limit=limit, refresh=refresh)
    qlib = to_qlib_code(code)
    df = df.copy()
    df["symbol"] = qlib
    return df.reset_index(drop=True)


def _derive_technical_signal(
    analysis: dict[str, Any],
    narrative: dict[str, Any],
) -> dict[str, Any]:
    """Map analysis to 偏多/谨慎/中性 and suggested action."""
    tech = analysis["technical"]
    ret20 = analysis["returns"].get("20d") or 0
    score = 0

    if tech["ma_alignment"] == "多头排列":
        score += 2
    elif tech["ma_alignment"] == "空头排列":
        score -= 2

    if tech.get("rsi_zone") == "超卖":
        score += 1
    elif tech.get("rsi_zone") == "超买":
        score -= 1

    if ret20 > 0.05:
        score += 1
    elif ret20 < -0.05:
        score -= 1

    narrative_stance = str(narrative.get("stance") or "中性")
    if narrative_stance == "偏多":
        score += 1
    elif narrative_stance == "谨慎":
        score -= 1

    stance: StockStance
    action: str
    if score >= 2:
        stance = "偏多"
        action = "buy"
    elif score <= -2:
        stance = "谨慎"
        action = "sell"
    else:
        stance = "中性"
        action = "hold"

    reasons = [
        f"均线：{tech['ma_alignment']}",
        f"叙事立场：{narrative_stance}",
    ]
    if tech.get("rsi_14") is not None:
        reasons.append(f"RSI={tech['rsi_14']}（{tech.get('rsi_zone')}）")
    if ret20 is not None:
        reasons.append(f"近20日涨跌：{ret20:.2%}")
    reasons.append(f"综合得分 {score}")

    return {
        "stance": stance,
        "action": action,
        "score": score,
        "confidence": round(min(abs(score) / 4.0, 1.0), 2),
        "reasons": reasons,
    }


def _pick_ml_latest(ml_analysis: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ml_analysis or not ml_analysis.get("enabled"):
        return None
    if ml_analysis.get("algorithm") == "both" and ml_analysis.get("models"):
        comp = ml_analysis.get("comparison") or {}
        pref = comp.get("preferred_by_ic")
        models = ml_analysis.get("models") or {}
        if pref and pref in models and models[pref].get("enabled"):
            return models[pref]
        for m in models.values():
            if m.get("enabled"):
                return m
        return None
    if ml_analysis.get("latest"):
        return ml_analysis
    return None


def _ml_signal_to_stance(ml_signal: str | None) -> StockStance | None:
    if not ml_signal:
        return None
    if "偏多" in ml_signal:
        return "偏多"
    if "偏空" in ml_signal:
        return "谨慎"
    return "中性"


def _merge_stock_signals(
    technical: dict[str, Any],
    ml_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    """Combine rule-based technical signal with qlib ML output (A-share stances)."""
    tech_stance: StockStance = technical["stance"]
    tech_action = technical["action"]
    score = int(technical.get("score", 0))

    ml_block = _pick_ml_latest(ml_analysis)
    ml_stance: StockStance | None = None
    ml_signal: str | None = None
    ml_pred: float | None = None
    if ml_block:
        latest = ml_block.get("latest") or {}
        ml_signal = latest.get("signal")
        ml_pred = latest.get("predicted_return")
        ml_stance = _ml_signal_to_stance(ml_signal)
        if ml_stance == "偏多":
            score += 1
        elif ml_stance == "谨慎":
            score -= 1

    if score >= 2:
        combined_stance: StockStance = "偏多"
        combined_action = "buy"
    elif score <= -2:
        combined_stance = "谨慎"
        combined_action = "sell"
    else:
        combined_stance = "中性"
        combined_action = "hold"

    reasons = list(technical.get("reasons") or [])
    if ml_signal:
        reasons.append(f"qlib ML：{ml_signal}")
        if ml_pred is not None:
            reasons.append(f"ML 预测收益代理：{ml_pred:.4f}")

    agreement = "一致" if ml_stance == tech_stance else ("分歧" if ml_stance else "仅技术面")

    return {
        "stance": combined_stance,
        "action": combined_action,
        "score": score,
        "confidence": min(abs(score) / 5.0, 1.0),
        "technical": {"stance": tech_stance, "action": tech_action},
        "ml": {
            "stance": ml_stance,
            "signal": ml_signal,
            "predicted_return": ml_pred,
        },
        "agreement": agreement,
        "reasons": reasons,
    }


def _compact_output(sid: str, output: dict[str, Any]) -> dict[str, Any]:
    """Strip bulky nested objects from API responses."""
    if sid == "technical":
        return {
            k: output[k]
            for k in ("stance", "action", "score", "confidence", "reasons")
            if k in output
        }
    if sid == "announcement_scan":
        return {
            k: output[k]
            for k in (
                "code",
                "items_count",
                "items_new",
                "max_score",
                "high_impact",
                "impact_stance",
                "top_title",
                "top_keywords",
                "fetch_error",
            )
            if k in output
        }
    if sid == "qlib_ml":
        ml = output.get("ml_analysis") or {}
        comb = output.get("combined_signal") or {}
        compact: dict[str, Any] = {
            "skipped": output.get("skipped"),
            "reason": output.get("reason"),
            "stance": comb.get("stance"),
            "agreement": comb.get("agreement"),
            "ml_signal": (comb.get("ml") or {}).get("signal"),
            "ml_enabled": ml.get("enabled"),
        }
        oos = output.get("oos_summary") or compact_oos_for_ui(output.get("oos_protocol"))
        if oos:
            compact["oos_summary"] = {
                k: oos[k]
                for k in (
                    "protocol_type",
                    "gate_passed",
                    "test_ic",
                    "direction_accuracy",
                    "headline",
                )
                if k in oos
            }
            if oos.get("markdown"):
                compact["oos_markdown"] = oos["markdown"]
        return compact
    if sid == "zipline_strategy":
        compact = {
            k: output[k]
            for k in ("strategy_id", "target_pct", "position", "bullish", "metrics")
            if k in output
        }
        oos = output.get("oos_summary")
        if oos:
            compact["oos_summary"] = {
                k: oos[k]
                for k in (
                    "protocol_type",
                    "gate_passed",
                    "test_ic",
                    "direction_accuracy",
                    "headline",
                )
                if k in oos
            }
            if oos.get("markdown"):
                compact["oos_markdown"] = oos["markdown"]
        return compact
    if sid == "var_symbol":
        narr = output.get("narrative") or {}
        return {
            "var_99_pct": output.get("var_99_pct"),
            "var_99_cny": output.get("var_99_cny"),
            "var_ratio": output.get("var_ratio"),
            "headline": narr.get("headline"),
        }
    if sid == ADVICE_STEP:
        return {
            k: output[k]
            for k in (
                "stance",
                "action",
                "score",
                "confidence",
                "suggested_position_pct",
                "risk_level",
                "var_gate_triggered",
                "signal_agreement",
                "headline",
                "bullets",
                "advice",
                "price_guidance",
                "disclaimer",
            )
            if k in output
        }
    return output


def summarize_step(sid: str, output: dict[str, Any], *, status: str) -> str:
    if status == "skipped":
        return str(output.get("reason") or "已跳过")
    if status == "error":
        return "执行失败"
    if sid == "technical":
        return f"{output.get('stance')} · score {output.get('score')}"
    if sid == "announcement_scan":
        if output.get("fetch_error") and not output.get("items_count"):
            return f"拉取失败：{output.get('fetch_error')}"
        hi = " · 高影响" if output.get("high_impact") else ""
        title = str(output.get("top_title") or "无命中公告")[:40]
        return f"{output.get('impact_stance')} · 分数 {output.get('max_score', 0)}{hi} · {title}"
    if sid == "qlib_ml":
        if output.get("skipped"):
            return f"跳过：{output.get('reason', '样本不足')}"
        oos = output.get("oos_summary") or {}
        oos_tag = ""
        if oos.get("gate_passed") is True:
            oos_tag = " · OOS✓"
        elif oos.get("gate_passed") is False:
            oos_tag = " · OOS✗"
        return f"{output.get('stance')} · {output.get('agreement')}{oos_tag}"
    if sid == "zipline_strategy":
        oos = output.get("oos_summary") or {}
        oos_tag = ""
        if oos.get("gate_passed") is True:
            oos_tag = " · OOS✓"
        elif oos.get("gate_passed") is False:
            oos_tag = " · OOS✗"
        return (
            f"{output.get('strategy_id')} → 仓位 {float(output.get('target_pct') or 0) * 100:.0f}%"
            f"{oos_tag}"
        )
    if sid == "var_symbol":
        return (
            f"99% VaR {float(output.get('var_99_pct') or 0) * 100:.2f}%"
            f" · {output.get('var_99_cny')} 元"
        )
    if sid == ADVICE_STEP:
        pg = output.get("price_guidance") or {}
        if pg.get("available"):
            return (
                f"{output.get('headline', '')} · "
                f"参考买 {pg.get('entry_price')} / 止损 {pg.get('stop_loss_price')} / "
                f"止盈 {pg.get('take_profit_price')}"
            )
        return str(output.get("headline") or "")
    return status


def _step_technical(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    df: pd.DataFrame = ctx["df"]
    analysis = analyze_ohlcv(df)
    narrative = build_narrative(analysis)
    signal = _derive_technical_signal(analysis, narrative)
    ctx["_analysis"] = analysis
    ctx["_narrative"] = narrative
    ctx["_technical_signal"] = signal
    return {
        "analysis": analysis,
        "narrative": narrative,
        "technical_signal": signal,
        "stance": signal.get("stance"),
        "action": signal.get("action"),
        "score": signal.get("score", 0),
        "confidence": signal.get("confidence", 0),
        "reasons": signal.get("reasons", []),
    }


def _step_announcement_scan(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    from quant_rd_tool.stock_announcement_radar import (
        derive_announcement_impact,
        items_for_symbol,
        scan_symbol_announcements,
    )

    code = ctx["code"]
    data_dir = ctx["data_dir"]
    min_score = int(params.get("min_score") or 40)
    notice_limit = int(params.get("notice_limit") or 15)
    high_impact_min = int(params.get("high_impact_min") or 70)
    refresh = params.get("refresh", True) is not False
    persist = params.get("persist", True) is not False

    if refresh:
        out = scan_symbol_announcements(
            code,
            data_dir=data_dir,
            notice_limit=notice_limit,
            min_score=min_score,
            persist=persist,
        )
    else:
        items = items_for_symbol(code, data_dir=data_dir, limit=notice_limit)
        items = [i for i in items if int(i.get("score") or 0) >= min_score]
        impact = derive_announcement_impact(items, high_impact_min=high_impact_min)
        out = {
            "code": code,
            "items": items[:10],
            "items_count": len(items),
            "items_new": 0,
            "fetch_error": None,
            **impact,
        }

    ctx["_announcement_scan"] = out
    return out


def _step_qlib_ml(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    df: pd.DataFrame = ctx["df"]
    symbol = ctx["symbol"]
    data_dir = ctx["data_dir"]
    code = to_ak_code(symbol)
    qlib_code = to_qlib_code(code)
    root = stock_root(data_dir, code)
    qlib_dir = qlib_path(root)
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work["symbol"] = qlib_code
    QlibDataDumper(qlib_dir, freq="day").dump({qlib_code: work})
    start_date, end_date = format_period_bounds(work, ctx["timeframe"])
    algorithm: MlAlgorithm = params.get("algorithm", "both")  # type: ignore[assignment]
    if algorithm not in ("xgb", "lgb", "both"):
        algorithm = "both"
    ml = run_ml_analysis(
        str(qlib_dir.resolve()),
        qlib_code,
        start_date=start_date,
        end_date=end_date,
        num_bars=len(work),
        algorithm=algorithm,
        qlib_freq="day",
    )
    tech = ctx["steps"].get("technical", {}).get("output", {})
    if tech.get("technical_signal"):
        tech_signal = tech["technical_signal"]
    else:
        analysis = analyze_ohlcv(ctx["df"])
        narrative = build_narrative(analysis)
        tech_signal = _derive_technical_signal(analysis, narrative)
    if ml.get("skipped") or ml.get("enabled") is False:
        reason = ml.get("reason") or "qlib ML skipped"
        combined = _merge_stock_signals(tech_signal, None)
        return {
            "ml_analysis": ml,
            "combined_signal": combined,
            "stance": combined.get("stance"),
            "agreement": combined.get("agreement"),
            "skipped": True,
            "reason": reason,
        }
    combined = _merge_stock_signals(tech_signal, ml)
    oos_protocol = ml.get("oos_protocol")
    oos_summary = compact_oos_for_ui(oos_protocol)
    return {
        "ml_analysis": ml,
        "combined_signal": combined,
        "stance": combined.get("stance"),
        "agreement": combined.get("agreement"),
        "skipped": False,
        "oos_protocol": oos_protocol,
        "oos_summary": oos_summary,
    }


def _step_zipline_strategy(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    df: pd.DataFrame = ctx["df"]
    strategy_id = str(params.get("strategy_id") or "ma_crossover")
    capital_base = float(params.get("capital_base") or 100_000)
    strategy_params = params.get("strategy_params") or {}
    out = run_pandas_backtest(
        df,
        strategy_id=strategy_id,
        strategy_params=strategy_params,
        capital_base=capital_base,
        timeframe=ctx["timeframe"],
        symbol=to_ak_code(ctx["symbol"]),
        data_dir=ctx["data_dir"],
    )
    final = out.get("final_signal") or {}
    target = float(final.get("target_pct") or 0.0)
    oos_protocol = out.get("oos_protocol")
    oos_summary = compact_oos_for_ui(oos_protocol)
    return {
        "strategy_id": strategy_id,
        "engine": out.get("engine"),
        "final_signal": final,
        "target_pct": target,
        "position": final.get("position", "flat"),
        "metrics": out.get("metrics"),
        "bullish": target >= 0.5,
        "oos_protocol": oos_protocol,
        "oos_summary": oos_summary,
    }


def _step_var_symbol(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    levels = parse_confidence_levels(str(params.get("confidence") or "0.95,0.99"))
    lookback = int(params.get("lookback_bars") or 252)
    report = build_symbol_var_report_from_df(
        ctx["df"],
        ctx["symbol"],
        notional_cny=float(params.get("notional_cny") or 100_000),
        lookback_bars=lookback,
        horizon_days=int(params.get("horizon_days") or 1),
        data_dir=ctx["data_dir"],
        mc_n_sims=int(params.get("mc_n_sims") or 3000),
    )
    hi = report.get("metrics", {}).get("0.99") or report.get("metrics", {}).get("0.95") or {}
    var_pct = float(hi.get("var_pct") or 0.0)
    var_ratio = var_pct
    return {
        "var_report": report,
        "var_99_pct": var_pct,
        "var_99_cny": hi.get("var_cny"),
        "var_ratio": var_ratio,
        "narrative": report.get("narrative"),
    }


def _stance_to_score(stance: str | None) -> int:
    if stance in ("偏多", "看涨"):
        return 1
    if stance in ("谨慎", "看跌"):
        return -1
    return 0


def _is_bullish_stance(stance: str) -> bool:
    return stance in ("偏多", "看涨")


def _is_bearish_stance(stance: str) -> bool:
    return stance in ("谨慎", "看跌")


def synthesize_advice(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    var_gate_pct = float(params.get("var_gate_pct") or 0.08)
    max_position_pct = float(params.get("max_position_pct") or 0.5)

    score = 0
    bullets: list[str] = []
    sources: dict[str, Any] = {}
    stances: list[str] = []

    tech = ctx["steps"].get("technical", {})
    if tech.get("status") == "ok":
        out = tech.get("output") or {}
        score += int(out.get("score") or 0)
        tech_stance = str(out.get("stance") or "中性")
        stances.append(tech_stance)
        sources["technical"] = {"stance": out.get("stance"), "score": out.get("score")}
        bullets.append(f"技术面：{out.get('stance')}（score {out.get('score')}）")

    ann = ctx["steps"].get("announcement_scan", {})
    if ann.get("status") == "ok":
        out = ann.get("output") or {}
        impact = str(out.get("impact_stance") or "中性")
        max_score = int(out.get("max_score") or 0)
        high_impact = bool(out.get("high_impact"))
        sources["announcement_scan"] = {
            "impact_stance": impact,
            "max_score": max_score,
            "high_impact": high_impact,
            "top_title": out.get("top_title"),
        }
        title = str(out.get("top_title") or "—")[:48]
        kw = "、".join((out.get("top_keywords") or [])[:3]) or "—"
        bullets.append(f"公告：{impact} · 分数 {max_score} · {title}（{kw}）")
        if impact != "中性":
            stances.append(impact)
        if impact == "谨慎":
            score -= 2 if high_impact else 1
        elif impact == "偏多":
            score += 1
    elif ann.get("status") == "skipped":
        bullets.append(f"公告扫描：跳过（{ann.get('error', '未运行')}）")

    ml = ctx["steps"].get("qlib_ml", {})
    if ml.get("status") == "ok":
        out = ml.get("output") or {}
        if out.get("skipped"):
            bullets.append(f"qlib ML：跳过（{out.get('reason', '样本不足')}）")
        else:
            comb = out.get("combined_signal") or {}
            ml_stance = (comb.get("ml") or {}).get("stance")
            if ml_stance:
                score += _stance_to_score(ml_stance)
                stances.append(str(ml_stance))
            comb_stance = str(comb.get("stance") or "")
            if comb_stance and comb_stance not in stances:
                stances.append(comb_stance)
            sources["qlib_ml"] = {"stance": comb.get("stance"), "agreement": comb.get("agreement")}
            bullets.append(f"qlib ML：{comb.get('stance')}（与技术面 {comb.get('agreement')}）")
    elif ml.get("status") == "skipped":
        bullets.append(f"qlib ML：跳过（{ml.get('error', '未运行')}）")

    strat = ctx["steps"].get("zipline_strategy", {})
    strategy_target = 0.0
    if strat.get("status") == "ok":
        out = strat.get("output") or {}
        strategy_target = float(out.get("target_pct") or 0.0)
        if strategy_target >= 0.5:
            score += 1
        elif strategy_target <= 0.1:
            score -= 1
        sources["zipline_strategy"] = {
            "strategy_id": out.get("strategy_id"),
            "target_pct": strategy_target,
        }
        bullets.append(
            f"策略 {out.get('strategy_id')}：目标仓位 {strategy_target * 100:.0f}%"
        )
        if strategy_target >= 0.5:
            stances.append("偏多")
        elif strategy_target <= 0.1:
            stances.append("谨慎")

    var_ratio = 0.0
    var_triggered = False
    var_step = ctx["steps"].get("var_symbol", {})
    if var_step.get("status") == "ok":
        out = var_step.get("output") or {}
        var_ratio = float(out.get("var_ratio") or 0.0)
        sources["var_symbol"] = {"var_99_pct": out.get("var_99_pct"), "var_99_cny": out.get("var_99_cny")}
        bullets.append(f"99% VaR：{var_ratio * 100:.2f}%（约 {out.get('var_99_cny')} 元）")
        if var_ratio > var_gate_pct:
            var_triggered = True
            score -= 1
            bullets.append(f"VaR 超阈（>{var_gate_pct * 100:.0f}%），建议降风险、勿加仓")

    if score >= 2:
        stance, action = "偏多", "buy"
    elif score <= -2:
        stance, action = "谨慎", "sell"
    else:
        stance, action = "中性", "hold"

    if var_triggered and stance == "偏多":
        stance, action = "中性", "hold"
        bullets.append("风险门控：VaR 偏高，看多信号已降级为观望")

    ann_out = (ctx["steps"].get("announcement_scan", {}).get("output") or {})
    if ann_out.get("high_impact") and ann_out.get("impact_stance") == "谨慎" and stance == "偏多":
        stance, action = "中性", "hold"
        bullets.append("公告门控：高影响负面公告，看多信号已降级为观望")

    base_position = max(0.0, min(max_position_pct, strategy_target if strategy_target > 0 else 0.25))
    if stance == "谨慎":
        suggested_position_pct = 0.0
    elif stance == "中性":
        suggested_position_pct = min(base_position, 0.15)
    else:
        suggested_position_pct = base_position
    if var_triggered:
        suggested_position_pct = min(suggested_position_pct, 0.1)

    confidence = min(abs(score) / 5.0, 1.0)
    if var_triggered:
        confidence *= 0.7

    bullish = sum(1 for s in stances if _is_bullish_stance(s))
    bearish = sum(1 for s in stances if _is_bearish_stance(s))
    if stances and (bullish == len(stances) or bearish == len(stances)):
        signal_agreement = "一致"
        confidence = min(confidence * 1.15, 1.0)
    elif bullish and bearish:
        signal_agreement = "分歧"
        confidence *= 0.85
    else:
        signal_agreement = "部分一致"

    if var_ratio > var_gate_pct * 1.5:
        risk_level = "高"
    elif var_ratio > var_gate_pct * 0.5:
        risk_level = "中"
    else:
        risk_level = "低"

    advice_map = {
        "偏多": "可考虑小仓位分批建仓，设置止损；仓位建议不超过建议上限。",
        "谨慎": "建议减仓或观望，避免逆势加仓。",
        "中性": "观望或维持现有仓位，等待多源信号一致后再行动。",
    }

    spot = float(ctx["df"]["close"].iloc[-1]) if len(ctx.get("df", [])) else 0.0
    realized_vol: float | None = None
    if tech.get("status") == "ok":
        analysis = (tech.get("output") or {}).get("analysis") or {}
        realized_vol = (analysis.get("risk") or {}).get("annualized_volatility")

    bollinger: dict[str, float | None] | None = None
    if len(ctx.get("df", [])):
        try:
            bollinger = (compute_technical_overlay(ctx["df"]).get("bollinger") or {})
        except Exception:
            bollinger = None

    advice_stance_for_iv = stance
    if stance == "偏多":
        advice_stance_for_iv = "看涨"
    elif stance == "谨慎":
        advice_stance_for_iv = "看跌"

    price_guidance = compute_iv_price_guidance(
        spot=spot,
        stance=advice_stance_for_iv,
        action=action,
        timeframe=str(ctx.get("timeframe") or "1d"),
        atm_iv=None,
        dte_days=None,
        iv_percentile=None,
        annualized_realized_vol=realized_vol,
        bollinger=bollinger,
        sl_sigma=float(params.get("sl_sigma") or 1.0),
        tp_sigma=float(params.get("tp_sigma") or 1.5),
        entry_sigma=float(params.get("entry_sigma") or 0.35),
        horizon_days=float(params["horizon_days"]) if params.get("horizon_days") else None,
    )

    if price_guidance.get("available"):
        vol_pct = float(price_guidance.get("atm_iv") or 0) * 100
        move_pct = float(price_guidance.get("expected_move_pct") or 0) * 100
        src = price_guidance.get("iv_source")
        src_label = {"options": "期权 IV", "realized": "历史波动", "default": "默认"}.get(str(src), str(src))
        bullets.append(
            f"波动参考价位（{src_label} {vol_pct:.1f}%，{price_guidance.get('horizon_days')} 日预期波动约 {move_pct:.1f}%）："
            f"参考买 {price_guidance['entry_price']}，"
            f"止损 {price_guidance['stop_loss_price']}（{float(price_guidance.get('stop_loss_pct') or 0) * 100:+.1f}%），"
            f"止盈 {price_guidance['take_profit_price']}（{float(price_guidance.get('take_profit_pct') or 0) * 100:+.1f}%）"
        )
        sources["price_guidance"] = {
            "entry_price": price_guidance.get("entry_price"),
            "stop_loss_price": price_guidance.get("stop_loss_price"),
            "take_profit_price": price_guidance.get("take_profit_price"),
            "atm_iv": price_guidance.get("atm_iv"),
            "iv_source": price_guidance.get("iv_source"),
        }

    code = to_ak_code(ctx["symbol"])
    qlib = to_qlib_code(code)
    headline = (
        f"{qlib} Workflow：{stance}（建议仓位 {suggested_position_pct * 100:.0f}%）"
        f"，风险等级 {risk_level}"
    )

    markdown_lines = [
        f"# A股 Workflow 投资建议 — {qlib}",
        "",
        f"**周期**：{ctx['timeframe']}",
        f"**生成**：{ctx.get('generated_at_beijing', '')}",
        "",
        f"## {headline}",
        "",
        advice_map[stance],
        "",
        "### 分步摘要",
        "",
    ]
    for b in bullets:
        markdown_lines.append(f"- {b}")
    if price_guidance.get("available"):
        markdown_lines.extend(
            [
                "",
                "### 波动参考价位",
                "",
                f"- 现价：**{price_guidance['spot']}**",
                f"- 参考买入/入场：**{price_guidance['entry_price']}**（{price_guidance.get('entry_note')}）",
                f"- 止损：**{price_guidance['stop_loss_price']}**",
                f"- 止盈：**{price_guidance['take_profit_price']}**",
                f"- 波动来源：{price_guidance.get('iv_source')}，年化 {float(price_guidance.get('atm_iv') or 0) * 100:.1f}%",
                f"- 持有周期约 {price_guidance.get('horizon_days')} 日，1σ 预期波动约 {float(price_guidance.get('expected_move_pct') or 0) * 100:.1f}%",
                "",
                f"_{price_guidance.get('disclaimer', '')}_",
            ]
        )
    markdown_lines.extend(
        [
            "",
            "### 风险",
            "",
            "- VaR 基于历史收益，不保证未来损失上限。",
            "- 短周期 ML / 策略信号可能快速反转。",
            "- 参考价位为统计估算，不构成投资建议。",
        ]
    )

    return {
        "stance": stance,
        "action": action,
        "score": score,
        "confidence": round(confidence, 4),
        "suggested_position_pct": round(suggested_position_pct, 4),
        "risk_level": risk_level,
        "var_gate_triggered": var_triggered,
        "signal_agreement": signal_agreement,
        "headline": headline,
        "bullets": bullets,
        "advice": advice_map[stance],
        "price_guidance": price_guidance,
        "sources": sources,
        "markdown": "\n".join(markdown_lines),
        "disclaimer": "研究用途，非投资建议。",
    }


_STEP_HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "technical": _step_technical,
    "announcement_scan": _step_announcement_scan,
    "qlib_ml": _step_qlib_ml,
    "zipline_strategy": _step_zipline_strategy,
    "var_symbol": _step_var_symbol,
}


def resolve_template_for_run(
    *,
    data_dir: str,
    template_id: str | None = None,
    template: dict[str, Any] | None = None,
    timeframe: str | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve effective template for a run: stored/inline template + UI overrides."""
    from quant_rd_tool.stock_workflow_storage import get_template, list_templates

    if template_id:
        tpl = get_template(data_dir, template_id)
        if not tpl:
            raise LookupError(f"Template not found: {template_id}")
        tpl = dict(tpl)
    elif template:
        tpl = dict(template)
        tpl["steps"] = normalize_template_steps(tpl.get("steps") or [])
    else:
        tpl = get_template(data_dir, "default-600519-1d")
        if not tpl:
            items = list_templates(data_dir)
            tpl = dict(items[0]) if items else None  # type: ignore[assignment]
        if not tpl:
            raise LookupError("No template available")
        tpl = dict(tpl)
    if timeframe:
        tpl["timeframe"] = timeframe
    if steps:
        tpl["steps"] = normalize_template_steps(steps)
    return tpl


def run_workflow(
    *,
    symbol: str,
    template: dict[str, Any],
    data_dir: str | None = None,
    refresh_ohlcv: bool = True,
    save: bool = True,
    progress_cb: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    code = to_ak_code(symbol.strip() or template.get("symbol_default", "600519"))
    qlib = to_qlib_code(code)
    tf = str(template.get("timeframe") or "1d")
    dd = data_dir or template.get("data_dir") or "data/stocks"
    steps_cfg = normalize_template_steps(template.get("steps") or [])

    def _notify(progress: float, message: str) -> None:
        if progress_cb:
            try:
                progress_cb(progress, message)
            except Exception:
                pass

    _notify(0.05, f"加载 {qlib} {tf} OHLCV")
    df = _load_ohlcv(code, data_dir=dd, timeframe=tf, refresh=refresh_ohlcv)
    if len(df) < 30:
        raise ValueError(f"insufficient OHLCV bars: {len(df)}")

    ctx: dict[str, Any] = {
        "symbol": qlib,
        "code": code,
        "timeframe": tf,
        "data_dir": dd,
        "df": df,
        "steps": {},
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_at_beijing": utc_now_beijing_str(),
    }

    enabled = [s for s in steps_cfg if s["enabled"]]
    exec_order = [s for s in enabled if s["id"] != ADVICE_STEP]
    exec_order.sort(key=lambda x: x["order"])
    advice_cfg = next((s for s in enabled if s["id"] == ADVICE_STEP), None)

    step_results: list[dict[str, Any]] = []
    timings: dict[str, float] = {}
    step_names = {s["id"]: str(s.get("name", s["id"])) for s in STEP_CATALOG}
    total_exec = max(1, len(exec_order))
    for i, step in enumerate(exec_order):
        sid = step["id"]
        handler = _STEP_HANDLERS.get(sid)
        if not handler:
            continue
        _notify(0.1 + 0.8 * i / total_exec, f"执行 {step_names.get(sid, sid)}")
        row: dict[str, Any] = {"id": sid, "order": step["order"]}
        t0 = time.perf_counter()
        try:
            output = handler(ctx, step.get("params") or {})
            elapsed = round(time.perf_counter() - t0, 3)
            timings[sid] = elapsed
            if output.get("skipped"):
                ctx["steps"][sid] = {"status": "skipped", "output": output}
                row["status"] = "skipped"
                row["output"] = _compact_output(sid, output)
                row["summary"] = summarize_step(sid, output, status="skipped")
            else:
                ctx["steps"][sid] = {"status": "ok", "output": output}
                row["status"] = "ok"
                row["output"] = _compact_output(sid, output)
                row["summary"] = summarize_step(sid, output, status="ok")
            row["elapsed_s"] = elapsed
        except Exception as exc:
            elapsed = round(time.perf_counter() - t0, 3)
            timings[sid] = elapsed
            ctx["steps"][sid] = {"status": "error", "error": str(exc)}
            row["status"] = "error"
            row["error"] = str(exc)
            row["summary"] = str(exc)[:200]
            row["elapsed_s"] = elapsed
        step_results.append(row)

    advice: dict[str, Any] | None = None
    if advice_cfg and advice_cfg.get("enabled", True):
        _notify(0.92, "合成投资建议")
        try:
            advice = synthesize_advice(ctx, advice_cfg.get("params") or {})
            ctx["steps"][ADVICE_STEP] = {"status": "ok", "output": advice}
            step_results.append(
                {
                    "id": ADVICE_STEP,
                    "order": advice_cfg["order"],
                    "status": "ok",
                    "output": _compact_output(ADVICE_STEP, advice),
                    "summary": summarize_step(ADVICE_STEP, advice, status="ok"),
                }
            )
        except Exception as exc:
            ctx["steps"][ADVICE_STEP] = {"status": "error", "error": str(exc)}
            step_results.append(
                {"id": ADVICE_STEP, "order": advice_cfg["order"], "status": "error", "error": str(exc)}
            )

    result: dict[str, Any] = {
        "run_id": str(uuid.uuid4()),
        "symbol": qlib,
        "code": code,
        "timeframe": tf,
        "data_dir": dd,
        "template_id": template.get("id"),
        "template_name": template.get("name"),
        "bars": len(df),
        "period": format_period_bounds(df.assign(date=pd.to_datetime(df["date"])), tf),
        "steps": step_results,
        "step_timings_s": timings,
        "advice": advice,
        "generated_at": ctx["generated_at"],
        "generated_at_beijing": ctx["generated_at_beijing"],
    }
    from quant_rd_tool.research_audit import record_research_run

    qlib_step = ctx["steps"].get("qlib_ml", {}).get("output") or {}
    result["audit_record"] = record_research_run(
        "stock_workflow",
        code=code,
        inputs={
            "template_id": template.get("id"),
            "template_name": template.get("name"),
            "timeframe": tf,
            "steps": [s["id"] for s in enabled],
        },
        outputs_summary={
            "stance": (advice or {}).get("stance"),
            "risk_level": (advice or {}).get("risk_level"),
            "oos_gate_passed": (qlib_step.get("oos_summary") or {}).get("gate_passed"),
        },
        data_dir=dd,
        run_id=result["run_id"],
    )
    if save:
        return save_run(dd, result)
    return result
