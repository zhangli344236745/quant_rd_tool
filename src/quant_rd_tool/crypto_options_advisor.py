"""Rule-based options vol suggestions (research only)."""

from __future__ import annotations

from typing import Any

DISCLAIMER = (
    "以下为基于隐含波动率规则的研究性提示，不构成投资建议。"
    "期权交易风险极高，请自行评估并控制仓位。"
)


def advise_item(row: dict[str, Any]) -> dict[str, Any]:
    base = row.get("base", "?")
    level = row.get("alert_level", "normal")
    pct = row.get("iv_percentile")
    chg = row.get("iv_change_24h_pct")
    iv = row.get("atm_iv")
    rank = row.get("rank")

    actions: list[str] = []
    risks: list[str] = []
    reasons: list[str] = []

    if row.get("error"):
        return {
            "base": base,
            "stance": "不可用",
            "summary": f"{base} 期权数据暂不可用：{row['error']}",
            "actions": ["稍后重试扫描或检查 Binance 期权 API 连通性。"],
            "risks": [DISCLAIMER],
            "confidence": 0.0,
        }

    if row.get("cold_start"):
        reasons.append("历史 IV 样本不足，分位与 24h 变化仅供参考。")

    if pct is not None:
        reasons.append(f"IV 历史分位约 {pct}%（近月 ATM mark IV {iv}）。")
    if chg is not None:
        reasons.append(f"24 小时 IV 变化约 {chg:+.1f}%。")
    if rank is not None:
        reasons.append(f"横向波动综合排名 #{rank}。")

    stance = "中性"
    confidence = 0.45

    high_pct = pct is not None and pct >= 80
    rising = chg is not None and chg >= 10
    falling = chg is not None and chg <= -10

    if level == "hot" or (high_pct and rising):
        stance = "波动溢价偏高"
        confidence = 0.72
        actions.append(
            f"{base} 期权隐含波动处于偏高且抬升区间，买方权利金昂贵，纯买入期权性价比偏低。"
        )
        actions.append(
            "若看多波动方向，可考虑小仓位跨式/宽跨并严格止损；更常见思路是卖出波动并配合现货或永续对冲。"
        )
        risks.append("IV 仍可能继续冲高，裸卖波动风险无限，需保证金与止损纪律。")
    elif high_pct and falling:
        stance = "波动均值回归观察"
        confidence = 0.65
        actions.append(
            f"{base} IV 分位偏高但 24h 回落，可关注波动回落是否持续，再评估卖 vol 策略窗口。"
        )
        risks.append("趋势行情下 IV 回落可能是短暂现象，勿盲目抄底卖权。")
    elif high_pct:
        stance = "高波动环境"
        confidence = 0.6
        actions.append(f"{base} IV 分位偏高，宜降低杠杆、拉宽止损，期权以对冲为主。")
    elif rising and not high_pct:
        stance = "波动升温"
        confidence = 0.55
        actions.append(f"{base} IV 快速上升但历史分位未极端，关注事件驱动与突破方向。")
    else:
        actions.append(f"{base} 期权波动未达告警阈值，可维持常规仓位管理。")

    if rank == 1 and level in ("hot", "elevated"):
        actions.insert(0, f"{base} 为当前观察列表中波动最突出标的，优先跟踪。")

    summary = f"{base}：{stance}。"
    if pct is not None and chg is not None:
        summary += f" IV 分位 {pct}%，24h {chg:+.1f}%。"

    return {
        "base": base,
        "stance": stance,
        "summary": summary,
        "actions": actions,
        "risks": risks + [DISCLAIMER],
        "reasons": reasons,
        "confidence": confidence,
    }


def build_scan_advice(scan: dict[str, Any]) -> dict[str, Any]:
    items = scan.get("items") or []
    per_symbol = [advise_item(row) for row in items]
    hot = [a for a in per_symbol if a.get("stance") not in ("中性", "不可用")]
    overview = "当前无显著高波动期权标的。"
    if hot:
        names = ", ".join(a["base"] for a in hot[:3])
        overview = f"波动偏高标的：{names}。详见各标的建议。"
    return {
        "overview": overview,
        "disclaimer": DISCLAIMER,
        "advice": per_symbol,
    }
