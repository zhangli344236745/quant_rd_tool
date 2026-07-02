"""Cross-view between spot/ML stance and Polymarket implied probabilities."""

from __future__ import annotations

from typing import Any


def prediction_stance_from_prob(prob: float | None) -> str:
    if prob is None:
        return "中性"
    if prob >= 0.6:
        return "偏多"
    if prob <= 0.4:
        return "偏空"
    return "中性"


def synthesize_prediction_cross_view(
    *,
    spot_stance: str,
    spot_action: str,
    pm_ctx: dict[str, Any],
) -> dict[str, Any]:
    if not pm_ctx.get("enabled"):
        return {
            "alignment": "unavailable",
            "summary": "Polymarket 预测市场数据暂不可用，以下研判仅基于 K 线/ML/期权。",
            "notes": [],
        }

    top = pm_ctx.get("top_market") or {}
    prob = top.get("implied_prob_yes")
    pred_stance = prediction_stance_from_prob(prob if prob is None else float(prob))
    notes: list[str] = []
    if top.get("question"):
        notes.append(f"代表市场：{top['question']}")
    if prob is not None:
        notes.append(f"YES 隐含概率约 {float(prob) * 100:.1f}%。")
    if top.get("volume24hr"):
        notes.append(f"24h 成交量约 {float(top['volume24hr']):,.0f} USDC。")
    mc = int(pm_ctx.get("market_count") or 0)
    if mc > 1:
        notes.append(f"共匹配 {mc} 个 {pm_ctx.get('base')} 相关预测市场。")

    arb = pm_ctx.get("arb_summary") or {}
    if arb.get("opportunity_hits"):
        notes.append(
            f"相关市场当前有 {arb['opportunity_hits']} 条套利机会"
            + (f"，最佳 edge {arb['best_edge_bps']} bps。" if arb.get("best_edge_bps") else "。")
        )

    alignment = "补充"
    summary_parts: list[str] = []

    if spot_stance == "看涨":
        if pred_stance == "偏多" or (prob is not None and float(prob) >= 0.55):
            alignment = "共振"
            summary_parts.append("现货/ML 偏多，预测市场定价同样偏乐观，方向一致性较高。")
        elif pred_stance == "偏空" or (prob is not None and float(prob) <= 0.45):
            alignment = "分歧"
            summary_parts.append(
                "技术面/ML 偏多，但 Polymarket 隐含概率偏空：注意事件风险与叙事反转，不宜盲目加杠杆。"
            )
        else:
            alignment = "补充"
            summary_parts.append("现货偏多而预测市场定价中性，事件驱动不确定性仍存。")
    elif spot_stance == "看跌":
        if pred_stance == "偏空" or (prob is not None and float(prob) <= 0.45):
            alignment = "共振"
            summary_parts.append("技术面偏空且预测市场定价偏悲观，下行叙事一致。")
        elif pred_stance == "偏多":
            alignment = "分歧"
            summary_parts.append("技术面偏空但预测市场仍定价偏乐观，可能存在反弹或政策预期。")
        else:
            summary_parts.append("技术面偏空，预测市场未给出强方向，宜谨慎减仓。")
    else:
        if prob is not None and float(prob) >= 0.65:
            summary_parts.append(f"现货方向中性而预测市场偏多（{float(prob)*100:.0f}%）：关注事件催化。")
        elif prob is not None and float(prob) <= 0.35:
            summary_parts.append(f"现货中性而预测市场偏空（{float(prob)*100:.0f}%）：注意尾部风险。")
        else:
            summary_parts.append("现货与预测市场均未给出强方向，宜观望。")

    return {
        "alignment": alignment,
        "summary": " ".join(summary_parts),
        "notes": notes,
        "prediction_stance": pred_stance,
        "implied_prob_yes": prob,
        "spot_stance": spot_stance,
        "spot_action": spot_action,
    }
