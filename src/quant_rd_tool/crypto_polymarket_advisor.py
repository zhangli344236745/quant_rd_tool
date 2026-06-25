"""Polymarket opportunity scoring, win-rate estimation, and investment advice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from quant_rd_tool.crypto_polymarket_analytics import edge_trend, leaderboard

if TYPE_CHECKING:
    from quant_rd_tool.crypto_polymarket_arb import PolymarketArbConfig

RecommendationLevel = Literal["strong_buy", "buy", "watch", "pass"]

_STRATEGY_CERTAINTY: dict[str, float] = {
    "binary_ask": 0.98,
    "binary_bid": 0.88,
    "multi_ask": 0.82,
}

_LEVEL_LABEL: dict[str, str] = {
    "strong_buy": "强烈推荐",
    "buy": "建议参与",
    "watch": "观望等待",
    "pass": "暂不推荐",
}


@dataclass
class AdvisorConfig:
    min_win_rate: float = 0.60
    history_hours: float = 168.0
    strong_buy_win_rate: float = 0.75
    buy_win_rate: float = 0.60
    watch_win_rate: float = 0.45
    min_profit_usd: float = 0.10


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def persistence_rate(condition_id: str, strategy_type: str | None, *, hours: float) -> float:
    hits = edge_trend(condition_id, hours=hours, strategy_type=strategy_type)
    if not hits:
        return 0.35
    if len(hits) >= 10:
        return 0.95
    if len(hits) >= 5:
        return 0.80
    if len(hits) >= 3:
        return 0.65
    if len(hits) >= 2:
        return 0.50
    return 0.40


def execution_confidence(row: dict[str, Any], target_shares: float) -> float:
    fillable = float(row.get("fillable_shares") or row.get("size_cap") or 0)
    if fillable <= 0 or target_shares <= 0:
        return 0.0
    fill_ratio = _clamp(fillable / target_shares)
    slippage = abs(float(row.get("slippage_bps") or 0))
    slip_penalty = _clamp(1.0 - slippage / 80.0)
    depth_levels = int(row.get("depth_levels") or 1)
    depth_bonus = _clamp(depth_levels / 3.0, 0.5, 1.0)
    return round(fill_ratio * slip_penalty * depth_bonus, 4)


def estimate_win_rate(row: dict[str, Any], *, history_hours: float, target_shares: float) -> dict[str, Any]:
    st = str(row.get("strategy_type") or "binary_ask")
    certainty = _STRATEGY_CERTAINTY.get(st, 0.75)
    cid = str(row.get("condition_id") or "")
    persist = persistence_rate(cid, st, hours=history_hours) if cid else 0.35
    execution = execution_confidence(row, target_shares)
    composite = round(certainty * 0.40 + persist * 0.25 + execution * 0.35, 4)
    return {
        "strategy_certainty": certainty,
        "persistence_rate": persist,
        "execution_confidence": execution,
        "win_rate": composite,
        "win_rate_pct": round(composite * 100, 1),
    }


def profit_analysis(
    row: dict[str, Any],
    *,
    target_shares: float,
    taker_fee_bps: float,
) -> dict[str, Any]:
    st = str(row.get("strategy_type") or "binary_ask")
    fillable = float(row.get("fillable_shares") or row.get("size_cap") or 0)
    recommended_size = min(target_shares, fillable) if fillable > 0 else 0.0
    edge_at_size = float(row.get("edge_at_size") or row.get("edge") or 0)
    profit_at_size = float(row.get("profit_at_size_usd") or 0)
    if recommended_size > 0 and edge_at_size > 0 and profit_at_size <= 0:
        profit_at_size = edge_at_size * recommended_size

    if st == "binary_ask":
        ask_yes = float(row.get("vwap_yes") or row.get("ask_yes") or 0)
        ask_no = float(row.get("vwap_no") or row.get("ask_no") or 0)
        cost_per_share = ask_yes + ask_no
    elif st == "binary_bid":
        cost_per_share = 2.0 - float(row.get("vwap_bid_yes") or row.get("bid_yes") or 0) - float(
            row.get("vwap_bid_no") or row.get("bid_no") or 0
        )
    else:
        cost_per_share = float(row.get("outcome_sum") or sum(row.get("outcome_vwaps") or []) or 1.0)

    cost_usd = recommended_size * cost_per_share if recommended_size > 0 else 0.0
    fee_usd = cost_usd * taker_fee_bps / 10_000.0
    expected_profit = profit_at_size if profit_at_size > 0 else max(0.0, recommended_size * edge_at_size)
    net_profit = expected_profit - fee_usd if fee_usd > 0 else expected_profit
    roi_pct = (net_profit / cost_usd * 100.0) if cost_usd > 0 else 0.0

    return {
        "recommended_size_shares": round(recommended_size, 4),
        "cost_usd": round(cost_usd, 4),
        "fee_usd": round(fee_usd, 4),
        "expected_profit_usd": round(expected_profit, 4),
        "net_profit_usd": round(net_profit, 4),
        "roi_pct": round(roi_pct, 2),
        "edge_at_size_bps": row.get("edge_at_size_bps") or row.get("edge_bps"),
    }


def classify_recommendation(
    win_rate: float,
    profit: dict[str, Any],
    row: dict[str, Any],
    cfg: AdvisorConfig,
) -> RecommendationLevel:
    if not row.get("opportunity"):
        return "pass"
    net = float(profit.get("net_profit_usd") or 0)
    if net < cfg.min_profit_usd:
        return "pass"
    if win_rate >= cfg.strong_buy_win_rate and row.get("paper_tradable", True) and net >= cfg.min_profit_usd:
        return "strong_buy"
    if win_rate >= cfg.buy_win_rate:
        return "buy"
    if win_rate >= cfg.watch_win_rate:
        return "watch"
    return "pass"


def build_advice_text(
    level: RecommendationLevel,
    row: dict[str, Any],
    win: dict[str, Any],
    profit: dict[str, Any],
) -> str:
    st = str(row.get("strategy_type") or "binary_ask")
    parts: list[str] = []
    wr = win["win_rate_pct"]
    net = profit.get("net_profit_usd", 0)
    size = profit.get("recommended_size_shares", 0)

    if level == "strong_buy":
        parts.append(f"综合胜率 {wr}%，执行条件良好，属于高确定性套利。")
    elif level == "buy":
        parts.append(f"综合胜率 {wr}%，具备参与价值，建议控制仓位。")
    elif level == "watch":
        parts.append(f"综合胜率 {wr}%，边际尚可但持续性或深度不足，建议观望。")
    else:
        parts.append(f"综合胜率 {wr}%，当前不建议参与。")
        return "".join(parts)

    if st == "binary_ask":
        parts.append(f"建议纸面买入 YES+NO 共 {size} 份，")
    elif st == "binary_bid":
        parts.append(f"策略为双边卖出套利（仅扫描），理论规模 {size} 份，")
    else:
        parts.append(f"多结果全覆盖策略（仅扫描），理论规模 {size} 份，")

    parts.append(f"预估净利 {net:.2f} USDC（ROI {profit.get('roi_pct', 0):.1f}%）。")

    if win["persistence_rate"] >= 0.65:
        parts.append("历史命中频繁，机会重现率高。")
    elif win["persistence_rate"] < 0.45:
        parts.append("历史命中较少，需警惕一次性价差。")

    if win["execution_confidence"] < 0.5:
        parts.append("深度不足或滑点偏大，实际成交可能低于预估。")
    elif win["execution_confidence"] >= 0.8:
        parts.append("订单簿深度充足，滑点可控。")

    if st != "binary_ask":
        parts.append("该策略暂不支持纸面开仓，仅供研究。")

    parts.append("研究用途，非实盘建议；请自行评估合规与流动性风险。")
    return "".join(parts)


def score_opportunity(
    row: dict[str, Any],
    *,
    config: PolymarketArbConfig | None = None,
    advisor: AdvisorConfig | None = None,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_polymarket_arb import PolymarketArbConfig, load_config

    cfg = config or load_config()
    adv = advisor or AdvisorConfig()
    target = float(cfg.depth_target_shares)
    win = estimate_win_rate(row, history_hours=adv.history_hours, target_shares=target)
    profit = profit_analysis(row, target_shares=target, taker_fee_bps=cfg.taker_fee_bps)
    level = classify_recommendation(win["win_rate"], profit, row, adv)
    advice = build_advice_text(level, row, win, profit)
    score = round(
        win["win_rate"] * 40
        + _clamp(float(profit.get("roi_pct") or 0) / 5.0, 0, 20)
        + _clamp(float(row.get("edge_at_size_bps") or row.get("edge_bps") or 0) / 10.0, 0, 30)
        + (10 if level == "strong_buy" else 5 if level == "buy" else 0),
        2,
    )
    return {
        "condition_id": row.get("condition_id"),
        "question": row.get("question"),
        "strategy_type": row.get("strategy_type"),
        "market_url": row.get("market_url"),
        "recommendation": level,
        "recommendation_label": _LEVEL_LABEL[level],
        "score": score,
        "win_rate": win["win_rate"],
        "win_rate_pct": win["win_rate_pct"],
        "win_rate_breakdown": win,
        "profit_analysis": profit,
        "advice": advice,
        "paper_tradable": row.get("paper_tradable", row.get("strategy_type") in (None, "binary_ask")),
        "opportunity": bool(row.get("opportunity")),
    }


def build_recommendations(
    scan: dict[str, Any] | None = None,
    *,
    config: PolymarketArbConfig | None = None,
    advisor: AdvisorConfig | None = None,
    min_win_rate: float | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_polymarket_arb import load_config, load_latest_scan

    cfg = config or load_config()
    adv = advisor or AdvisorConfig()
    if min_win_rate is not None:
        adv = AdvisorConfig(
            min_win_rate=min_win_rate,
            history_hours=adv.history_hours,
            strong_buy_win_rate=adv.strong_buy_win_rate,
            buy_win_rate=adv.buy_win_rate,
            watch_win_rate=adv.watch_win_rate,
            min_profit_usd=adv.min_profit_usd,
        )
    latest = scan if scan is not None else load_latest_scan()
    items = list((latest or {}).get("items") or [])
    scored = [score_opportunity(r, config=cfg, advisor=adv) for r in items if r.get("opportunity")]
    scored.sort(key=lambda r: (float(r.get("score") or 0), float(r.get("win_rate") or 0)), reverse=True)

    high_win = [r for r in scored if float(r.get("win_rate") or 0) >= adv.min_win_rate]
    top_picks = high_win[:limit] if high_win else scored[:limit]

    lb = leaderboard(hours=adv.history_hours, limit=5)
    return {
        "generated_at": (latest or {}).get("scanned_at"),
        "scanned_at": (latest or {}).get("scanned_at"),
        "total_opportunities": len(scored),
        "high_win_rate_count": len(high_win),
        "min_win_rate": adv.min_win_rate,
        "top_picks": top_picks,
        "all_scored": scored,
        "persistent_leaders": lb,
        "disclaimer": "以下为基于历史命中、深度与策略类型的研究性评分，不构成投资建议。",
    }
