"""Per-strike call purchase hints from probabilities, spot view, and IV regime."""

from __future__ import annotations

from typing import Any, Literal

PurchaseVerdict = Literal["可考虑买入", "观望", "不建议买入"]

_PURCHASE_DISCLAIMER = (
    "行权价建议仅综合概率差、现货方向与 IV 环境，未计手续费、滑点与流动性；不构成投资建议。"
)


def advise_call_purchase(
    row: dict[str, Any],
    *,
    spot: float,
    spot_stance: str = "中性",
    iv_alert_level: str = "normal",
    iv_percentile: float | None = None,
) -> dict[str, Any]:
    """
    Research hint for buying the listed call at strike K.

    Uses model vs implied expiry ITM gap, moneyness, spot stance, IV alert.
    """
    strike = float(row.get("strike") or 0)
    moneyness = float(row.get("moneyness_pct") or 0)
    model_exp = (row.get("model") or {}).get("expiry_itm_call")
    impl_exp = (row.get("implied") or {}).get("expiry_itm_call")
    edge = row.get("edge_expiry")
    if edge is None and model_exp is not None and impl_exp is not None:
        edge = float(model_exp) - float(impl_exp)

    reasons: list[str] = []
    score = 0  # higher => more buy-friendly

    stance = (spot_stance or "中性").strip()
    alert = (iv_alert_level or "normal").strip().lower()
    high_iv = alert in ("hot", "elevated") or (iv_percentile is not None and iv_percentile >= 80)

    if stance == "看跌":
        return _pack(
            "不建议买入",
            "现货/综合信号偏空，不宜新建买方 Call（可考虑对冲或观望）。",
            reasons + ["方向与买 Call 不一致"],
            row,
        )

    if strike <= 0 or spot <= 0:
        return _pack("观望", "缺少有效行权价或现货价。", reasons, row)

    if moneyness > 8:
        reasons.append(f"深度虚值约 {moneyness:.1f}%，到期 ITM 概率偏低，属高杠杆博弈。")
        score -= 2
    elif moneyness > 3:
        reasons.append(f"虚值约 {moneyness:.1f}%，需较大涨幅才能实质 ITM。")
        score -= 1
    elif abs(moneyness) <= 1.5:
        reasons.append("接近 ATM，Delta 与 Gamma 暴露适中。")
        score += 1

    if high_iv:
        reasons.append(f"IV 环境偏热（{alert}），买方权利金成本高。")
        score -= 2
    else:
        score += 1

    if edge is not None:
        e = float(edge)
        if e >= 0.06:
            reasons.append(f"模型到期 ITM 概率高于隐含约 {e * 100:.1f}pp，定价偏保守。")
            score += 2
        elif e >= 0.02:
            reasons.append(f"模型略高于隐含（+{e * 100:.1f}pp）。")
            score += 1
        elif e <= -0.06:
            reasons.append(f"隐含概率高于模型约 {-e * 100:.1f}pp，Call 偏贵。")
            score -= 2
        elif e <= -0.02:
            score -= 1

    if model_exp is not None:
        p = float(model_exp)
        if p >= 0.55 and moneyness <= 2:
            reasons.append(f"模型估计到期 ITM 概率约 {p * 100:.0f}%。")
            score += 1
        elif p < 0.25 and moneyness > 0:
            reasons.append(f"模型到期 ITM 仅约 {p * 100:.0f}%，赔率差。")
            score -= 1

    if stance == "看涨":
        reasons.append("现货/综合信号偏多，买 Call 方向一致。")
        score += 2
    elif stance == "中性":
        reasons.append("现货方向中性，买 Call 需依赖波动或突破。")
        score -= 1

    if score >= 3 and not high_iv:
        verdict: PurchaseVerdict = "可考虑买入"
        summary = "概率与方向尚可、IV 未极端，可小仓评估买方 Call（设止损/限仓）。"
    elif score <= -2 or (high_iv and score < 2):
        verdict = "不建议买入"
        summary = "IV 偏贵或概率/方向不支持，优先现货/永续或卖波动结构。"
    else:
        verdict = "观望"
        summary = "信号混合，宜等待更好入场或改用价差降低权利金。"

    return _pack(verdict, summary, reasons, row)


def _pack(
    verdict: PurchaseVerdict,
    summary: str,
    reasons: list[str],
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "summary": summary,
        "reasons": reasons,
        "strike": row.get("strike"),
        "symbol": row.get("symbol"),
    }


def enrich_strike_report_with_advice(
    report: dict[str, Any],
    *,
    spot_stance: str = "中性",
    iv_alert_level: str = "normal",
    iv_percentile: float | None = None,
) -> dict[str, Any]:
    """Add per-row purchase advice and ladder-level summary to strike probability report."""
    spot = float(report.get("spot") or 0)
    rows = report.get("rows") or []
    enriched: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        advice = advise_call_purchase(
            row,
            spot=spot,
            spot_stance=spot_stance,
            iv_alert_level=iv_alert_level,
            iv_percentile=iv_percentile,
        )
        enriched.append({**row, "purchase": advice})

    report["rows"] = enriched
    report["purchase_summary"] = summarize_purchase_advice(
        enriched,
        spot_stance=spot_stance,
        iv_alert_level=iv_alert_level,
    )
    report["purchase_disclaimer"] = _PURCHASE_DISCLAIMER
    return report


def summarize_purchase_advice(
    rows: list[dict[str, Any]],
    *,
    spot_stance: str,
    iv_alert_level: str,
) -> dict[str, Any]:
    """Pick best candidate strike and overall guidance."""
    candidates = [
        r
        for r in rows
        if (r.get("purchase") or {}).get("verdict") == "可考虑买入"
    ]
    best: dict[str, Any] | None = None
    best_edge = -999.0
    for r in candidates:
        e = r.get("edge_expiry")
        if e is None:
            continue
        if float(e) > best_edge:
            best_edge = float(e)
            best = r

    avoid = sum(1 for r in rows if (r.get("purchase") or {}).get("verdict") == "不建议买入")
    consider = len(candidates)

    if best:
        p = best.get("purchase") or {}
        headline = (
            f"相对更可关注 {best.get('strike')} Call：{p.get('summary', '')}"
        )
    elif consider:
        headline = f"共 {consider} 档为「可考虑买入」，请结合表格细则与仓位纪律。"
    elif avoid == len(rows) and rows:
        headline = "当前各档买 Call 性价比均偏差，不建议追涨买入期权。"
    else:
        headline = "多数行权价宜观望；高 IV 或方向不明时优先控制权利金暴露。"

    return {
        "headline": headline,
        "spot_stance": spot_stance,
        "iv_alert_level": iv_alert_level,
        "consider_count": consider,
        "avoid_count": avoid,
        "best_strike": best.get("strike") if best else None,
        "best_contract": best.get("symbol") if best else None,
    }
