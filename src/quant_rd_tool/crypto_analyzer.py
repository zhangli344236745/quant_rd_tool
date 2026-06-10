"""Crypto technical analysis and bullish/bearish stance."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from quant_rd_tool.openbb_equity import compute_technical_overlay
from quant_rd_tool.stock_analyzer import _period_return, _risk_metrics, _rsi

CryptoStance = Literal["看涨", "看跌", "中性"]


def analyze_crypto_ohlcv(df: pd.DataFrame) -> dict[str, Any]:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values("date").set_index("date")
    close = work["close"].astype(float)
    daily_ret = close.pct_change()

    latest = float(close.iloc[-1])
    sma20 = close.rolling(20).mean()
    sma60 = close.rolling(60).mean()
    rsi = _rsi(close)

    ma_signal = "震荡"
    if pd.notna(sma20.iloc[-1]) and pd.notna(sma60.iloc[-1]):
        if latest > sma20.iloc[-1] > sma60.iloc[-1]:
            ma_signal = "多头排列"
        elif latest < sma20.iloc[-1] < sma60.iloc[-1]:
            ma_signal = "空头排列"

    rsi_val = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else None
    rsi_zone = "中性"
    if rsi_val is not None:
        if rsi_val >= 70:
            rsi_zone = "超买"
        elif rsi_val <= 30:
            rsi_zone = "超卖"

    overlay = compute_technical_overlay(df)

    return {
        "symbol": str(df["symbol"].iloc[0]),
        "period": {
            "start": str(work.index.min().date()),
            "end": str(work.index.max().date()),
            "bars": int(len(work)),
        },
        "price": {
            "latest_close": round(latest, 6),
            "period_high": round(float(close.max()), 6),
            "period_low": round(float(close.min()), 6),
            "pct_from_high": round(float(latest / close.max() - 1), 6),
        },
        "returns": {
            "1d": _period_return(close, 1),
            "5d": _period_return(close, 5),
            "20d": _period_return(close, 20),
            "60d": _period_return(close, 60),
        },
        "risk": _risk_metrics(daily_ret),
        "technical": {
            "ma_alignment": ma_signal,
            "close_vs_sma20": round(float(latest / sma20.iloc[-1] - 1), 6)
            if pd.notna(sma20.iloc[-1])
            else None,
            "rsi_14": round(rsi_val, 2) if rsi_val is not None else None,
            "rsi_zone": rsi_zone,
            "macd_trend": (overlay.get("macd") or {}).get("trend"),
            "bollinger_zone": (overlay.get("bollinger") or {}).get("zone"),
        },
    }


def derive_trading_signal(analysis: dict[str, Any]) -> dict[str, Any]:
    """Map analysis to 看涨/看跌/中性 and suggested action."""
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

    macd = tech.get("macd_trend") or ""
    if "多头" in macd:
        score += 1
    elif "空头" in macd:
        score -= 1

    if ret20 > 0.05:
        score += 1
    elif ret20 < -0.05:
        score -= 1

    stance: CryptoStance
    action: str
    if score >= 2:
        stance = "看涨"
        action = "buy"
    elif score <= -2:
        stance = "看跌"
        action = "sell"
    else:
        stance = "中性"
        action = "hold"

    confidence = min(abs(score) / 4.0, 1.0)
    return {
        "stance": stance,
        "action": action,
        "score": score,
        "confidence": round(confidence, 2),
        "reasons": _signal_reasons(tech, ret20, score),
    }


def _signal_reasons(tech: dict, ret20: float, score: int) -> list[str]:
    reasons: list[str] = []
    reasons.append(f"均线：{tech['ma_alignment']}")
    if tech.get("rsi_14") is not None:
        reasons.append(f"RSI={tech['rsi_14']}（{tech.get('rsi_zone')}）")
    if tech.get("macd_trend"):
        reasons.append(f"MACD：{tech['macd_trend']}")
    reasons.append(f"近20日涨跌：{ret20:.2%}")
    reasons.append(f"综合得分 {score}")
    return reasons


def _return_window_label(timeframe: str) -> str:
    tf = (timeframe or "1d").strip().lower()
    if tf in ("1d", "day", "d"):
        return "日"
    return "根 K 线"


def _fmt_pct(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val:.2%}"


def _extract_ml_summary(ml_analysis: dict[str, Any] | None) -> dict[str, Any]:
    if not ml_analysis:
        return {"available": False}
    if ml_analysis.get("skipped"):
        return {"available": False, "reason": ml_analysis.get("reason", "已跳过")}
    from quant_rd_tool.crypto_ml import _pick_ml_latest

    block = _pick_ml_latest(ml_analysis)
    if not block or not block.get("enabled"):
        return {"available": False, "reason": "模型未启用"}
    latest = block.get("latest") or {}
    tm = block.get("test_metrics") or {}
    interp = block.get("interpretation") or {}
    return {
        "available": True,
        "signal": latest.get("signal"),
        "predicted_return": latest.get("predicted_return"),
        "ic": tm.get("ic"),
        "direction_accuracy": tm.get("direction_accuracy"),
        "summary": interp.get("summary"),
    }


def build_investment_brief(
    analysis: dict[str, Any],
    signal: dict[str, Any],
    *,
    combined_signal: dict[str, Any] | None = None,
    ml_analysis: dict[str, Any] | None = None,
    pair: str = "",
    timeframe: str = "1d",
    options_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Multi-section investment direction memo (not just bullish/bearish label)."""
    combined = combined_signal or signal
    price = analysis["price"]
    tech = analysis["technical"]
    risk = analysis.get("risk") or {}
    returns = analysis.get("returns") or {}
    stance = combined.get("stance", signal["stance"])
    action = combined.get("action", signal["action"])
    conf = combined.get("confidence", signal.get("confidence", 0))
    agreement = combined.get("agreement", "")
    win = _return_window_label(timeframe)
    display_pair = pair or analysis.get("symbol", "")

    latest = price["latest_close"]
    hi, lo = price["period_high"], price["period_low"]
    pct_hi = price.get("pct_from_high")
    ml = _extract_ml_summary(ml_analysis)

    sections: list[dict[str, Any]] = []

    # 1. Conclusion
    stance_meaning = {
        "看涨": "多维度信号偏强，可考虑顺势参与，但仍需仓位与止损纪律。",
        "看跌": "动能与结构偏弱，宜降风险、避免逆势加仓。",
        "中性": "多空证据均不充分或相互抵消，宜观望或维持仓位，等待结构明朗。",
    }[stance]
    conclusion_paras = [
        (
            f"综合研判为 **{stance}**（操作建议：{action}），置信度约 {conf:.0%}。"
            f"{stance_meaning}"
        ),
    ]
    if agreement:
        conclusion_paras.append(
            f"技术面 {combined.get('technical', {}).get('stance', signal['stance'])}，"
            f"机器学习 {combined.get('ml', {}).get('stance') or '未参与'}，"
            f"二者 **{agreement}**。"
        )
    sections.append(
        {
            "title": "结论：「{}」在说什么".format(stance),
            "paragraphs": conclusion_paras,
        }
    )

    # 2. Price structure
    struct_lines = [
        f"现价约 **{latest:,.2f}**，样本区间高/低 **{hi:,.2f} / {lo:,.2f}**。",
    ]
    if pct_hi is not None:
        struct_lines.append(f"距区间高点约 **{pct_hi:.1%}**。")
    if latest > (hi + lo) / 2:
        struct_lines.append("价格位于区间中上部，偏强整理或高位回落后的中段。")
    elif latest < (hi + lo) / 2:
        struct_lines.append("价格位于区间中下部，偏弱整理或回调后的中段，非明确底部确认。")
    else:
        struct_lines.append("价格接近区间中枢，典型震荡格局。")
    if risk.get("max_drawdown") is not None:
        struct_lines.append(f"样本内最大回撤约 **{risk['max_drawdown']:.1%}**，波动需纳入仓位管理。")
    sections.append({"title": "价格结构", "paragraphs": struct_lines})

    # 3. Multi-dimension
    dim_bullets: list[str] = []
    ma = tech.get("ma_alignment", "—")
    dim_bullets.append(
        f"**趋势（均线）**：{ma}。"
        + (
            " 无明确顺势做多依据。"
            if ma == "震荡"
            else (" 顺势做多逻辑增强。" if ma == "多头排列" else " 顺势做空/减仓逻辑增强。")
        )
    )
    macd = tech.get("macd_trend") or "—"
    if "空头" in str(macd):
        dim_bullets.append(f"**动能（MACD）**：{macd}，短期卖压仍在，不宜仅凭小幅下跌抄底。")
    elif "多头" in str(macd):
        dim_bullets.append(f"**动能（MACD）**：{macd}，短期动能偏多，可配合均线观察是否延续。")
    else:
        dim_bullets.append(f"**动能（MACD）**：{macd}。")

    rsi = tech.get("rsi_14")
    rsi_zone = tech.get("rsi_zone", "—")
    boll = tech.get("bollinger_zone") or "—"
    dim_bullets.append(f"**RSI**：{rsi}（{rsi_zone}）。")
    if "下轨" in str(boll) and rsi_zone != "超卖":
        dim_bullets.append(
            f"**布林带**：{boll}。存在超跌反弹可能，但趋势未扭转时反弹持续性存疑。"
        )
    else:
        dim_bullets.append(f"**布林带**：{boll}。")

    r5, r20, r60 = returns.get("5d"), returns.get("20d"), returns.get("60d")
    dim_bullets.append(
        f"**短期收益**（近 5/20/60 {win}）：{_fmt_pct(r5)} / {_fmt_pct(r20)} / {_fmt_pct(r60)}。"
    )

    if ml.get("available"):
        ic = ml.get("ic")
        da = ml.get("direction_accuracy")
        pred = ml.get("predicted_return")
        dim_bullets.append(
            f"**机器学习**：信号 {ml.get('signal')}，预测收益代理 {pred}；"
            f"测试集 IC={ic}，方向命中率={da}。"
            + (
                " 指标接近随机，不宜单独作为方向依据。"
                if ic is not None and abs(float(ic)) < 0.03
                else ""
            )
        )
    elif ml.get("reason"):
        dim_bullets.append(f"**机器学习**：未启用（{ml['reason']}）。")
    else:
        dim_bullets.append("**机器学习**：未参与本次研判。")

    sections.append({"title": "多维度拆解", "bullets": dim_bullets})

    opt = options_context or {}
    if opt.get("enabled"):
        opt_bullets: list[str] = []
        item = opt.get("scan_item") or {}
        if item.get("atm_iv") is not None:
            opt_bullets.append(f"近月 ATM IV 约 **{float(item['atm_iv']) * 100:.1f}%**。")
        if item.get("iv_percentile") is not None:
            opt_bullets.append(f"IV 历史分位 **{item['iv_percentile']}%**（告警 {item.get('alert_level')}）。")
        if item.get("iv_change_24h_pct") is not None:
            opt_bullets.append(f"24h IV 变化 **{item['iv_change_24h_pct']:+.1f}%**。")
        if item.get("contract"):
            opt_bullets.append(f"参考合约：`{item['contract']}`。")
        if opt.get("peer_rank") is not None and opt.get("peer_count"):
            opt_bullets.append(
                f"配置标的横向波动排名 **#{opt['peer_rank']}/{opt['peer_count']}**。"
            )
        if opt.get("hottest_peer") and opt.get("hottest_peer") != opt.get("base"):
            opt_bullets.append(f"综合 IV 最高标的：**{opt['hottest_peer']}**。")
        cross = opt.get("cross_view") or {}
        if cross.get("summary"):
            opt_bullets.append(cross["summary"])
        adv = opt.get("advice") or {}
        if adv.get("summary"):
            opt_bullets.append(adv["summary"])
        for a in (adv.get("actions") or [])[:3]:
            opt_bullets.append(a)
        vc = opt.get("venue_compare") or {}
        aligned = vc.get("aligned") if isinstance(vc, dict) else None
        if isinstance(aligned, dict) and aligned.get("available"):
            ac = aligned.get("comparison") or {}
            opt_bullets.append(
                f"**跨所同到期**（{aligned.get('expiry_date')}）："
                f"Binance vs Deribit IV 差 **{ac.get('iv_spread_pp'):+.1f}pp**"
                f"（{ac.get('richer_venue')} 偏高）。"
            )
            if ac.get("summary"):
                opt_bullets.append(ac["summary"])
        sp = opt.get("strategy_pack") or {}
        if sp.get("headline"):
            opt_bullets.append(f"**期权策略框架**：{sp['headline']}。")
        ladder = opt.get("strike_ladder") or {}
        if isinstance(ladder, dict) and ladder.get("rows"):
            ps = ladder.get("purchase_summary") or {}
            if ps.get("headline"):
                opt_bullets.append(f"**买 Call 摘要**：{ps['headline']}")
            for r in (ladder.get("rows") or [])[:5]:
                pur = r.get("purchase") or {}
                if not pur.get("verdict"):
                    continue
                opt_bullets.append(
                    f"K={r.get('strike')}：{pur.get('verdict')} — {pur.get('summary', '')}"
                )
        sections.append({"title": "期权波动率（Binance × Deribit）", "bullets": opt_bullets})
    elif opt.get("error"):
        sections.append(
            {
                "title": "期权波动率（Binance）",
                "bullets": [f"本次未纳入：{opt.get('error')}"],
            }
        )

    # 4. Position scenarios
    scenarios: list[dict[str, str]] = []
    if stance == "看涨":
        scenarios = [
            {"role": "已有多单", "text": "可持有或小幅加仓，止损设在关键支撑下方，避免追高重仓。"},
            {"role": "空仓", "text": "可分批试多，等待回踩确认或突破放量再加仓。"},
            {"role": "短线", "text": "顺势为主，跌破短期均线或 MACD 转弱则减仓。"},
        ]
    elif stance == "看跌":
        scenarios = [
            {"role": "已有多单", "text": "考虑减仓或收紧止损，避免逆势摊平。"},
            {"role": "空仓", "text": "观望为主，不宜盲目抄底；若做空需严格止损。"},
            {"role": "短线", "text": "反弹至均线压力可考虑减多或轻仓空，注意布林下轨附近勿追空。"},
        ]
    else:
        scenarios = [
            {
                "role": "已有多单",
                "text": "持有但不加仓；止损可设在区间下沿或成本下方固定比例；"
                "加仓需 MACD 转多、RSI 回升至 50 上方并站稳均线。",
            },
            {
                "role": "空仓",
                "text": "不追空、不急于抄底；可等待放量突破均线 + MACD 金叉，或缩量回踩支撑二次确认。",
            },
            {
                "role": "短线/波段",
                "text": "更适合区间内小仓位高抛低吸，而非重仓赌单边；"
                "现价若近布林下轨，偏多等反弹至均线压力再减，而非重仓赌 V 反。",
            },
        ]
    sections.append({"title": "按持仓场景的操作倾向", "scenarios": scenarios})

    # 5. Signal upgrade
    upgrades = [
        {"condition": "均线转多头 + MACD 多头 + RSI 回升至 50 上方", "bias": "偏多 → 可考虑分批建多"},
        {"condition": "均线空头 + MACD 空头 + RSI 超买", "bias": "偏空 → 减仓或不做多"},
        {"condition": "放量跌破区间下沿", "bias": "偏空 → 止损/降风险优先"},
        {"condition": "ML 测试集 IC 持续为正且信号偏多", "bias": "增强看多（需持续验证，不可单根 K 线决策）"},
    ]
    sections.append({"title": "何时会改变方向判断", "upgrades": upgrades})

    one_liner = (
        f"{display_pair}：{stance}（{action}）— "
        f"价 {latest:,.0f}，{ma}，{macd}；"
        f"{'ML 无显著边际' if ml.get('available') and ml.get('ic') is not None and abs(float(ml['ic'])) < 0.03 else '详见多维拆解'}。"
    )

    markdown = _brief_sections_to_markdown(sections, one_liner, timeframe)

    return {
        "sections": sections,
        "one_liner": one_liner,
        "markdown": markdown,
    }


def _brief_sections_to_markdown(
    sections: list[dict[str, Any]], one_liner: str, timeframe: str
) -> str:
    lines = ["## 投资方向说明（详细）", ""]
    if timeframe and timeframe not in ("1d", "day"):
        lines.append(
            f"> 数据周期：**{timeframe}**；时间均为**北京时间**；「近 N 根」指 K 线根数，非自然日。"
        )
        lines.append("")
    for sec in sections:
        lines.append(f"### {sec['title']}")
        lines.append("")
        for p in sec.get("paragraphs") or []:
            if p:
                lines.append(p)
                lines.append("")
        for b in sec.get("bullets") or []:
            lines.append(f"- {b}")
        for sc in sec.get("scenarios") or []:
            lines.append(f"- **{sc['role']}**：{sc['text']}")
        for up in sec.get("upgrades") or []:
            lines.append(f"- 若 {up['condition']} → {up['bias']}")
        lines.append("")
    lines.extend(["### 一句话", "", one_liner, ""])
    return "\n".join(lines)


def build_crypto_narrative(
    analysis: dict[str, Any],
    signal: dict[str, Any],
    *,
    combined_signal: dict[str, Any] | None = None,
    ml_analysis: dict[str, Any] | None = None,
    pair: str = "",
    timeframe: str = "1d",
    options_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sym = analysis["symbol"]
    price = analysis["price"]
    combined = combined_signal or signal
    stance = combined["stance"]
    action = combined["action"]

    summary = (
        f"{sym} 最新价 {price['latest_close']}，研判 **{stance}**（建议操作：{action}），"
        f"信号置信度约 {combined.get('confidence', signal.get('confidence', 0)):.0%}。"
    )

    observations = list(combined.get("reasons") or signal.get("reasons") or [])
    risks = [
        "加密货币波动极大，杠杆与合约风险更高。",
        "短周期（如 5m）信号变化快，需执行纪律，不宜重仓赌方向。",
        "机器学习在单标的短周期上可能接近随机，勿单独作为开仓依据。",
        "自动交易可能因滑点、限频、API 故障导致偏离预期。",
        "不构成投资建议；实盘前请用测试网或 dry-run 验证。",
    ]

    advice_map = {
        "看涨": "可考虑小仓位分批建仓，设置止损；勿追高重仓。",
        "看跌": "可考虑减仓或观望，避免逆势加仓。",
        "中性": "建议观望或维持现有仓位，等待趋势明朗；详见下方「投资方向说明」。",
    }

    brief = build_investment_brief(
        analysis,
        signal,
        combined_signal=combined,
        ml_analysis=ml_analysis,
        pair=pair,
        timeframe=timeframe,
        options_context=options_context,
    )

    opt = options_context or {}
    if opt.get("enabled"):
        cross = opt.get("cross_view") or {}
        if cross.get("summary"):
            summary += f" {cross['summary']}"
        for n in cross.get("notes") or []:
            observations.append(f"[期权] {n}")
        adv = opt.get("advice") or {}
        for a in adv.get("actions") or []:
            observations.append(f"[期权建议] {a}")
        risks.append("期权波动与方向可能背离；卖方策略存在尾部风险。")
        if opt.get("alert_level") in ("hot", "elevated"):
            risks.append("当前 IV 偏高，买方权利金成本显著，勿忽视时间价值损耗。")
        ladder = opt.get("strike_ladder") or {}
        if isinstance(ladder, dict) and ladder.get("purchase_disclaimer"):
            risks.append(str(ladder["purchase_disclaimer"]))

    return {
        "stance": stance,
        "action": action,
        "summary": summary,
        "observations": observations,
        "advice": advice_map[stance],
        "investment_brief": brief,
        "risks": risks,
        "disclaimer": "仅供量化研究学习，不构成投资建议。",
    }


def _strip_md(text: str) -> str:
    return (text or "").replace("**", "").strip()


def _fmt_pct_simple(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2%}"
    except (TypeError, ValueError):
        return "—"


_ACTION_LABELS = {"buy": "买入", "sell": "卖出", "hold": "观望"}


def build_crypto_ui_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Compact, plain-language summary for API / Web UI."""
    narrative = report.get("narrative") or {}
    analysis = report.get("analysis") or {}
    combined = report.get("combined_signal") or report.get("signal") or {}
    price = analysis.get("price") or {}
    tech = analysis.get("technical") or {}
    returns = analysis.get("returns") or {}
    risk = analysis.get("risk") or {}
    brief = narrative.get("investment_brief") or {}
    action = str(narrative.get("action") or combined.get("action") or "hold")

    price_lines = [
        f"最新价约 {price.get('latest_close', '—')}",
        f"样本区间高/低 {price.get('period_high', '—')} / {price.get('period_low', '—')}",
    ]
    if price.get("pct_from_high") is not None:
        price_lines.append(f"距区间高点 {_fmt_pct_simple(price.get('pct_from_high'))}")

    tech_lines = [
        f"均线排列：{tech.get('ma_alignment', '—')}",
        f"MACD：{tech.get('macd_trend', '—')}",
        f"RSI(14)：{tech.get('rsi_14', '—')}（{tech.get('rsi_zone', '—')}）",
        f"布林带：{tech.get('bollinger_zone', '—')}",
    ]
    ret_label = "根 K 线" if str(report.get("timeframe", "1d")) not in ("1d", "day") else "日"
    tech_lines.append(
        f"近 5/20 {ret_label}涨跌：{_fmt_pct_simple(returns.get('5d'))} / {_fmt_pct_simple(returns.get('20d'))}"
    )
    if risk.get("max_drawdown") is not None:
        tech_lines.append(f"样本最大回撤 {_fmt_pct_simple(risk.get('max_drawdown'))}")

    ml_block = combined.get("ml") or {}
    tech_stance = (combined.get("technical") or {}).get("stance") or combined.get("stance")
    ml_stance = ml_block.get("stance") or "未参与"

    return {
        "symbol": report.get("symbol") or analysis.get("symbol"),
        "pair": report.get("pair"),
        "timeframe": report.get("timeframe"),
        "period": report.get("period"),
        "headline": _strip_md(brief.get("one_liner") or narrative.get("summary") or ""),
        "summary": _strip_md(narrative.get("summary") or ""),
        "stance": narrative.get("stance") or combined.get("stance"),
        "action": action,
        "action_label": _ACTION_LABELS.get(action, action),
        "advice": narrative.get("advice"),
        "confidence": combined.get("confidence"),
        "agreement": combined.get("agreement"),
        "technical_stance": tech_stance,
        "ml_stance": ml_stance,
        "price_snapshot": {
            "latest": price.get("latest_close"),
            "period_high": price.get("period_high"),
            "period_low": price.get("period_low"),
            "pct_from_high": price.get("pct_from_high"),
        },
        "price_lines": price_lines,
        "technical_lines": tech_lines,
        "observations": narrative.get("observations") or [],
        "risks": narrative.get("risks") or [],
        "brief_sections": brief.get("sections") or [],
        "disclaimer": narrative.get("disclaimer"),
    }
