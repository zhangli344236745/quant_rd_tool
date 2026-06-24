"""Configurable crypto analysis workflow: technical + qlib + strategy + VaR → advice."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import time
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analysis import crypto_root, format_period_bounds
from quant_rd_tool.crypto_analyzer import analyze_crypto_ohlcv, derive_trading_signal
from quant_rd_tool.crypto_ml import merge_crypto_signals, run_crypto_ml_analysis
from quant_rd_tool.crypto_time import utc_now_beijing_str
from quant_rd_tool.crypto_var import build_symbol_var_report_from_df, parse_confidence_levels
from quant_rd_tool.crypto_workflow_price_levels import compute_iv_price_guidance
from quant_rd_tool.crypto_workflow_storage import save_run
from quant_rd_tool.openbb_equity import compute_technical_overlay
from quant_rd_tool.crypto_zipline_runner import run_pandas_backtest
from quant_rd_tool.qlib_dump import QlibDataDumper
from quant_rd_tool.qlib_ml import MlAlgorithm

STEP_CATALOG: list[dict[str, Any]] = [
    {
        "id": "technical",
        "name": "技术面分析",
        "description": "均线、RSI、MACD、布林带等综合技术信号",
        "params_schema": {},
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
            "notional_usdt": {"type": "number", "default": 10_000},
            "lookback_bars": {"type": "integer", "default": 252},
            "horizon_days": {"type": "integer", "default": 1},
            "confidence": {"type": "string", "default": "0.95,0.99"},
            "mc_n_sims": {"type": "integer", "default": 3000},
        },
    },
    {
        "id": "options_vol",
        "name": "期权波动率",
        "description": "Binance 期权 IV、skew 与现货×期权交叉视图",
        "params_schema": {},
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
    from quant_rd_tool.crypto_storage import load_ohlcv_csv, ohlcv_csv_path

    root = crypto_root(data_dir, symbol)
    root.mkdir(parents=True, exist_ok=True)
    csv_file = ohlcv_csv_path(root, timeframe)
    if not refresh and csv_file.is_file():
        df = load_ohlcv_csv(csv_file)
        if df is not None and len(df) >= 30:
            return df.tail(limit).reset_index(drop=True)
    df = cxt.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df.to_csv(csv_file, index=False)
    return df


def _compact_output(sid: str, output: dict[str, Any]) -> dict[str, Any]:
    """Strip bulky nested objects from API responses."""
    if sid == "technical":
        return {
            k: output[k]
            for k in ("stance", "action", "score", "confidence", "reasons")
            if k in output
        }
    if sid == "qlib_ml":
        ml = output.get("ml_analysis") or {}
        comb = output.get("combined_signal") or {}
        return {
            "skipped": output.get("skipped"),
            "reason": output.get("reason"),
            "stance": comb.get("stance"),
            "agreement": comb.get("agreement"),
            "ml_signal": (comb.get("ml") or {}).get("signal"),
            "ml_enabled": ml.get("enabled"),
        }
    if sid == "zipline_strategy":
        return {
            k: output[k]
            for k in ("strategy_id", "target_pct", "position", "bullish", "metrics")
            if k in output
        }
    if sid == "var_symbol":
        narr = output.get("narrative") or {}
        return {
            "var_99_pct": output.get("var_99_pct"),
            "var_99_usdt": output.get("var_99_usdt"),
            "var_ratio": output.get("var_ratio"),
            "headline": narr.get("headline"),
        }
    if sid == "options_vol":
        opt = output.get("options_vol") or {}
        scan = output.get("scan_item") or opt.get("scan_item") or {}
        cross = output.get("cross_view") or opt.get("cross_view") or {}
        return {
            "enabled": output.get("enabled"),
            "atm_iv": scan.get("atm_iv"),
            "iv_percentile": scan.get("iv_percentile"),
            "cross_summary": cross.get("summary"),
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
    if sid == "qlib_ml":
        if output.get("skipped"):
            return f"跳过：{output.get('reason', '样本不足')}"
        cache_tag = "（缓存）" if output.get("cache_hit") else ""
        return f"{output.get('stance')} · {output.get('agreement')}{cache_tag}"
    if sid == "zipline_strategy":
        return f"{output.get('strategy_id')} → 仓位 {float(output.get('target_pct') or 0) * 100:.0f}%"
    if sid == "var_symbol":
        return f"99% VaR {float(output.get('var_99_pct') or 0) * 100:.2f}% · {output.get('var_99_usdt')} USDT"
    if sid == "options_vol":
        if not output.get("enabled"):
            return "期权数据不可用"
        scan = output.get("scan_item") or (output.get("options_vol") or {}).get("scan_item") or {}
        cross = output.get("cross_view") or (output.get("options_vol") or {}).get("cross_view") or {}
        iv = scan.get("atm_iv")
        if iv is not None:
            return f"ATM IV {float(iv) * 100:.1f}%"
        return cross.get("summary") or "已加载"
    if sid == ADVICE_STEP:
        pg = output.get("price_guidance") or {}
        if pg.get("available"):
            return (
                f"{output.get('headline', '')} · "
                f"参考买 {pg.get('entry_price')} / 止损 {pg.get('stop_loss_price')} / 止盈 {pg.get('take_profit_price')}"
            )
        return str(output.get("headline") or "")
    return status


def _step_technical(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    df: pd.DataFrame = ctx["df"]
    analysis = analyze_crypto_ohlcv(df)
    signal = derive_trading_signal(analysis)
    ctx["_analysis"] = analysis
    ctx["_technical_signal"] = signal
    return {
        "analysis": analysis,
        "technical_signal": signal,
        "stance": signal.get("stance"),
        "action": signal.get("action"),
        "score": signal.get("score", 0),
        "confidence": signal.get("confidence", 0),
        "reasons": signal.get("reasons", []),
    }


def _step_qlib_ml(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    from quant_rd_tool.crypto_storage import qlib_dir_for

    df: pd.DataFrame = ctx["df"]
    symbol = ctx["symbol"]
    timeframe = ctx["timeframe"]
    data_dir = ctx["data_dir"]
    root = crypto_root(data_dir, symbol)
    qlib_dir = qlib_dir_for(root, timeframe)
    qlib_code = cxt.to_qlib_code(symbol)
    qlib_freq = cxt.timeframe_to_qlib_freq(timeframe)
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    QlibDataDumper(qlib_dir, freq=qlib_freq).dump({qlib_code: work})
    start_date, end_date = format_period_bounds(work, timeframe)
    algorithm: MlAlgorithm = params.get("algorithm", "both")  # type: ignore[assignment]
    if algorithm not in ("xgb", "lgb", "both"):
        algorithm = "both"
    ml = run_crypto_ml_analysis(
        str(qlib_dir.resolve()),
        qlib_code,
        start_date=start_date,
        end_date=end_date,
        num_bars=len(work),
        algorithm=algorithm,
        timeframe=timeframe,
        use_cache=bool(params.get("use_cache", True)),
    )
    tech = ctx["steps"].get("technical", {}).get("output", {})
    if tech.get("technical_signal"):
        tech_signal = tech["technical_signal"]
    else:
        analysis = analyze_crypto_ohlcv(ctx["df"])
        tech_signal = derive_trading_signal(analysis)
    if ml.get("skipped") or ml.get("enabled") is False:
        reason = ml.get("reason") or "qlib ML skipped"
        combined = merge_crypto_signals(tech_signal, None)
        return {
            "ml_analysis": ml,
            "combined_signal": combined,
            "stance": combined.get("stance"),
            "agreement": combined.get("agreement"),
            "skipped": True,
            "reason": reason,
        }
    combined = merge_crypto_signals(tech_signal, ml)
    return {
        "ml_analysis": ml,
        "combined_signal": combined,
        "stance": combined.get("stance"),
        "agreement": combined.get("agreement"),
        "skipped": False,
        "cache_hit": bool(ml.get("cache_hit")),
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
        symbol=ctx["symbol"],
        data_dir=ctx["data_dir"],
    )
    final = out.get("final_signal") or {}
    target = float(final.get("target_pct") or 0.0)
    return {
        "strategy_id": strategy_id,
        "engine": out.get("engine"),
        "final_signal": final,
        "target_pct": target,
        "position": final.get("position", "flat"),
        "metrics": out.get("metrics"),
        "bullish": target >= 0.5,
    }


def _step_var_symbol(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    levels = parse_confidence_levels(str(params.get("confidence") or "0.95,0.99"))
    lookback = int(params.get("lookback_bars") or 252)
    report = build_symbol_var_report_from_df(
        ctx["df"],
        ctx["symbol"],
        notional_usdt=float(params.get("notional_usdt") or 10_000),
        lookback_bars=lookback,
        horizon_days=int(params.get("horizon_days") or 1),
        timeframe=ctx["timeframe"],
        confidence_levels=levels,
        mc_n_sims=int(params.get("mc_n_sims") or 3000),
    )
    hi = report.get("metrics", {}).get("0.99") or report.get("metrics", {}).get("0.95") or {}
    var_pct = float(hi.get("var_pct") or 0.0)
    notional = float(report.get("notional_usdt") or 1.0)
    var_ratio = var_pct  # var_pct is already loss fraction
    return {
        "var_report": report,
        "var_99_pct": var_pct,
        "var_99_usdt": hi.get("var_usdt"),
        "var_ratio": var_ratio,
        "narrative": report.get("narrative"),
    }


def _step_options_vol(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    from quant_rd_tool.crypto_options_integration import attach_options_to_report

    tech_out = ctx["steps"].get("technical", {}).get("output") or {}
    ml_out = ctx["steps"].get("qlib_ml", {}).get("output") or {}
    analysis = tech_out.get("analysis") or analyze_crypto_ohlcv(ctx["df"])
    technical_signal = tech_out.get("technical_signal") or derive_trading_signal(analysis)
    combined = ml_out.get("combined_signal") or merge_crypto_signals(
        technical_signal, ml_out.get("ml_analysis")
    )
    report = {
        "symbol": analysis.get("symbol") or ctx["symbol"],
        "pair": cxt.to_ccxt_symbol(ctx["symbol"]),
        "timeframe": ctx["timeframe"],
        "analysis": analysis,
        "technical_signal": technical_signal,
        "ml_analysis": ml_out.get("ml_analysis"),
        "combined_signal": combined,
        "signal": combined,
    }
    attach_options_to_report(report, data_dir=ctx["data_dir"], with_options_vol=True, persist_snapshot=False)
    opt = report.get("options_vol") or {}
    return {
        "options_vol": opt,
        "enabled": opt.get("enabled", False),
        "cross_view": opt.get("cross_view"),
        "scan_item": opt.get("scan_item"),
    }


def _stance_to_score(stance: str | None) -> int:
    if stance == "看涨":
        return 1
    if stance == "看跌":
        return -1
    return 0


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
            stances.append("看涨")
        elif strategy_target <= 0.1:
            stances.append("看跌")

    var_ratio = 0.0
    var_triggered = False
    var_step = ctx["steps"].get("var_symbol", {})
    if var_step.get("status") == "ok":
        out = var_step.get("output") or {}
        var_ratio = float(out.get("var_ratio") or 0.0)
        sources["var_symbol"] = {"var_99_pct": out.get("var_99_pct"), "var_99_usdt": out.get("var_99_usdt")}
        bullets.append(f"99% VaR：{var_ratio * 100:.2f}%（约 {out.get('var_99_usdt')} USDT）")
        if var_ratio > var_gate_pct:
            var_triggered = True
            score -= 1
            bullets.append(f"VaR 超阈（>{var_gate_pct * 100:.0f}%），建议降风险、勿加仓")

    opt = ctx["steps"].get("options_vol", {})
    if opt.get("status") == "ok":
        out = opt.get("output") or {}
        if out.get("enabled"):
            cross = out.get("cross_view") or {}
            if cross.get("summary"):
                bullets.append(f"期权：{cross['summary']}")
            sources["options_vol"] = {"cross_summary": cross.get("summary")}

    if score >= 2:
        stance, action = "看涨", "buy"
    elif score <= -2:
        stance, action = "看跌", "sell"
    else:
        stance, action = "中性", "hold"

    if var_triggered and stance == "看涨":
        stance, action = "中性", "hold"
        bullets.append("风险门控：VaR 偏高，看多信号已降级为观望")

    base_position = max(0.0, min(max_position_pct, strategy_target if strategy_target > 0 else 0.25))
    if stance == "看跌":
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

    bullish = sum(1 for s in stances if s == "看涨")
    bearish = sum(1 for s in stances if s == "看跌")
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
        "看涨": "可考虑小仓位分批建仓，设置止损；仓位建议不超过建议上限。",
        "看跌": "建议减仓或观望，避免逆势加仓。",
        "中性": "观望或维持现有仓位，等待多源信号一致后再行动。",
    }

    spot = float(ctx["df"]["close"].iloc[-1]) if len(ctx.get("df", [])) else 0.0
    atm_iv: float | None = None
    dte_days: float | None = None
    iv_percentile: float | None = None
    if opt.get("status") == "ok":
        out = opt.get("output") or {}
        opt_block = out.get("options_vol") or out
        scan = out.get("scan_item") or opt_block.get("scan_item") or {}
        if scan.get("atm_iv") is not None:
            atm_iv = float(scan["atm_iv"])
        if scan.get("dte") is not None:
            dte_days = float(scan["dte"])
        if scan.get("iv_percentile") is not None:
            iv_percentile = float(scan["iv_percentile"])

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

    price_guidance = compute_iv_price_guidance(
        spot=spot,
        stance=stance,
        action=action,
        timeframe=str(ctx.get("timeframe") or "1d"),
        atm_iv=atm_iv,
        dte_days=dte_days,
        iv_percentile=iv_percentile,
        annualized_realized_vol=realized_vol,
        bollinger=bollinger,
        sl_sigma=float(params.get("sl_sigma") or 1.0),
        tp_sigma=float(params.get("tp_sigma") or 1.5),
        entry_sigma=float(params.get("entry_sigma") or 0.35),
        horizon_days=float(params["horizon_days"]) if params.get("horizon_days") else None,
    )

    if price_guidance.get("available"):
        iv_pct = float(price_guidance.get("atm_iv") or 0) * 100
        move_pct = float(price_guidance.get("expected_move_pct") or 0) * 100
        src = price_guidance.get("iv_source")
        src_label = {"options": "期权 IV", "realized": "历史波动", "default": "默认"}.get(str(src), str(src))
        bullets.append(
            f"IV 价位参考（{src_label} {iv_pct:.1f}%，{price_guidance.get('horizon_days')} 日预期波动约 {move_pct:.1f}%）："
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

    headline = (
        f"{ctx['symbol']} Workflow：{stance}（建议仓位 {suggested_position_pct * 100:.0f}%）"
        f"，风险等级 {risk_level}"
    )

    markdown_lines = [
        f"# Crypto Workflow 投资建议 — {ctx['symbol']}",
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
                "### IV 参考价位",
                "",
                f"- 现价：**{price_guidance['spot']}**",
                f"- 参考买入/入场：**{price_guidance['entry_price']}**（{price_guidance.get('entry_note')}）",
                f"- 止损：**{price_guidance['stop_loss_price']}**",
                f"- 止盈：**{price_guidance['take_profit_price']}**",
                f"- IV 来源：{price_guidance.get('iv_source')}，ATM IV {float(price_guidance.get('atm_iv') or 0) * 100:.1f}%",
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
            "- IV 参考价位为统计估算，不构成投资建议。",
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
    "qlib_ml": _step_qlib_ml,
    "zipline_strategy": _step_zipline_strategy,
    "var_symbol": _step_var_symbol,
    "options_vol": _step_options_vol,
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
    from quant_rd_tool.crypto_workflow_storage import get_template, list_templates

    if template_id:
        tpl = get_template(data_dir, template_id)
        if not tpl:
            raise LookupError(f"Template not found: {template_id}")
        tpl = dict(tpl)
    elif template:
        tpl = dict(template)
        tpl["steps"] = normalize_template_steps(tpl.get("steps") or [])
    else:
        tpl = get_template(data_dir, "default-btc-1d")
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
    sym = symbol.strip().upper() or template.get("symbol_default", "BTC")
    tf = str(template.get("timeframe") or "1d")
    dd = data_dir or template.get("data_dir") or "data/crypto"
    steps_cfg = normalize_template_steps(template.get("steps") or [])

    def _notify(progress: float, message: str) -> None:
        if progress_cb:
            try:
                progress_cb(progress, message)
            except Exception:
                pass

    _notify(0.05, f"加载 {sym} {tf} OHLCV")
    df = _load_ohlcv(sym, data_dir=dd, timeframe=tf, refresh=refresh_ohlcv)
    if len(df) < 30:
        raise ValueError(f"insufficient OHLCV bars: {len(df)}")

    ctx: dict[str, Any] = {
        "symbol": sym,
        "timeframe": tf,
        "data_dir": dd,
        "df": df,
        "steps": {},
        "generated_at": now_iso(),
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
        "symbol": sym,
        "pair": cxt.to_ccxt_symbol(sym),
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
    if save:
        return save_run(dd, result)
    return result
