"""Turn backtest outputs into plain-language investment suggestions (research only)."""

from __future__ import annotations

from typing import Any


def build_advice(
    *,
    metrics: dict[str, float | None],
    holdings: list[dict[str, Any]],
    scores: list[dict[str, Any]],
    universe: list[str],
    start_date: str,
    end_date: str,
    strategy_desc: str,
) -> dict[str, Any]:
    """Generate structured advice; not licensed investment recommendation."""
    summary_parts: list[str] = []
    actions: list[str] = []
    risks: list[str] = []

    ann = metrics.get("annualized_return")
    mdd = metrics.get("max_drawdown")
    sharpe = metrics.get("sharpe_ratio")
    total = metrics.get("total_return")

    if total is not None:
        pct = total * 100
        summary_parts.append(
            f"回测区间 {start_date} 至 {end_date}，策略「{strategy_desc}」累计收益约 {pct:.2f}%。"
        )
    if ann is not None:
        summary_parts.append(f"年化收益约 {ann * 100:.2f}%。")
    if sharpe is not None:
        tone = "风险调整后表现尚可" if sharpe > 0.5 else "风险调整后表现偏弱"
        summary_parts.append(f"信息比率 {sharpe:.2f}，{tone}。")
    if mdd is not None:
        summary_parts.append(f"最大回撤约 {abs(mdd) * 100:.2f}%，需关注下行风险。")
        if abs(mdd) > 0.25:
            risks.append("历史最大回撤超过 25%，波动较大，不宜高杠杆。")

    if scores:
        leader = scores[0]
        laggard = scores[-1]
        ls = leader.get("score", leader.get("momentum_score", 0))
        lag = laggard.get("score", laggard.get("momentum_score", 0))
        actions.append(
            f"信号得分最高：{leader['code']}（{ls:.4f}），最低：{laggard['code']}（{lag:.4f}）。"
        )
        if ls > 0:
            actions.append(f"按策略逻辑，近期相对强势标的包括 {leader['code']}，可作观察池优先项。")
        if lag < 0:
            actions.append(f"弱势标的 {laggard['code']} 在轮动模型中更易被减仓，不宜盲目抄底。")

    if holdings:
        names = ", ".join(h["code"] for h in holdings[:3])
        actions.append(f"回测期末模拟持仓权重靠前：{names}。")
    else:
        actions.append("回测期末无明确持仓记录，请以最新信号重新评估。")

    excess = metrics.get("excess_annualized_return")
    if excess is not None:
        if excess > 0.02:
            actions.append("相对基准有正超额，策略在样本内具备一定选股效果。")
        elif excess < -0.02:
            actions.append("相对基准超额为负，可考虑降低仓位或优化因子参数。")
            risks.append("样本内跑输基准，直接实盘可能延续弱势。")

    risks.extend(
        [
            "以上结论仅基于历史数据回测，未来市场结构变化可能导致失效。",
            "未计入涨跌停无法成交、停牌、冲击成本等现实摩擦。",
            "不构成任何证券买卖建议，决策需结合基本面、流动性与个人风险承受能力。",
        ]
    )

    stance = _stance(metrics, scores)
    return {
        "stance": stance,
        "summary": " ".join(summary_parts) if summary_parts else "回测已完成，详见 metrics。",
        "actions": actions,
        "risks": risks,
        "disclaimer": "本工具输出仅供量化研究学习，不构成投资建议。",
        "monitored_symbols": universe,
    }


def _stance(metrics: dict[str, float | None], scores: list[dict[str, Any]]) -> str:
    ann = metrics.get("annualized_return")
    mdd = metrics.get("max_drawdown")
    if ann is None:
        return "中性"
    if ann > 0.08 and (mdd is None or abs(mdd) < 0.2):
        return "偏多（样本内）"
    if ann < 0 or (mdd is not None and abs(mdd) > 0.3):
        return "谨慎"
    top = scores[0].get("score", scores[0].get("momentum_score", 0)) if scores else 0
    if scores and top > 0.05:
        return "结构性偏多"
    return "中性"
