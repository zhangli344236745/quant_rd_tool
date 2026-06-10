"""Rule-based options strategy suggestions from IV regime and strike ladder."""

from __future__ import annotations

from typing import Any, Literal

StrategyKind = Literal[
    "sell_straddle",
    "sell_strangle",
    "buy_straddle",
    "bull_call_spread",
    "bear_put_spread",
    "buy_call",
    "buy_put",
    "iron_condor",
    "wait",
]

_DISCLAIMER = (
    "以下为研究性策略框架示意，未计手续费、保证金与流动性；不构成投资建议。"
)


def _round_strike(v: float) -> float:
    return round(v, 2)


def _atm_strike(spot: float, rows: list[dict[str, Any]]) -> float | None:
    if rows:
        return float(rows[len(rows) // 2].get("strike") or spot)
    # round to sensible step
    if spot >= 10000:
        step = 1000
    elif spot >= 1000:
        step = 100
    else:
        step = 10
    return _round_strike(round(spot / step) * step)


def suggest_strategies(
    *,
    scan_item: dict[str, Any] | None = None,
    strike_report: dict[str, Any] | None = None,
    spot_stance: str = "中性",
    spot: float | None = None,
    venue_compare: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Return 2–4 ranked strategy hints from IV scan row and optional strike ladder.
    """
    item = scan_item or {}
    base = str(item.get("base") or strike_report.get("base") or "?")
    alert = str(item.get("alert_level") or "normal").lower()
    pct = item.get("iv_percentile")
    chg = item.get("iv_change_24h_pct")
    atm_iv = item.get("atm_iv")
    high_iv = alert in ("hot", "elevated") or (pct is not None and float(pct) >= 80)
    low_iv = pct is not None and float(pct) <= 30
    rising = chg is not None and float(chg) >= 10
    falling = chg is not None and float(chg) <= -10

    s = spot or strike_report.get("spot") or item.get("underlying_price")
    try:
        spot_f = float(s) if s is not None else 0.0
    except (TypeError, ValueError):
        spot_f = 0.0

    rows = (strike_report or {}).get("rows") or []
    atm_k = _atm_strike(spot_f, rows) if spot_f > 0 else None
    stance = (spot_stance or "中性").strip()

    strategies: list[dict[str, Any]] = []

    def add(
        kind: StrategyKind,
        name: str,
        rationale: str,
        legs: list[dict[str, Any]],
        *,
        score: float,
        risk: str = "中",
    ) -> None:
        strategies.append(
            {
                "id": kind,
                "name": name,
                "rationale": rationale,
                "legs": legs,
                "risk_level": risk,
                "score": score,
                "base": base,
            }
        )

    if item.get("error") or atm_iv is None:
        add(
            "wait",
            "观望",
            f"{base} 期权数据不可用，暂不建议新建期权仓位。",
            [],
            score=0.0,
            risk="低",
        )
        return strategies

    wing_pct = 0.05
    if atm_k and spot_f > 0:
        call_wing = _round_strike(atm_k * (1 + wing_pct))
        put_wing = _round_strike(atm_k * (1 - wing_pct))
        lower_spread = _round_strike(atm_k * 0.98)
        upper_spread = _round_strike(atm_k * 1.02)
    else:
        call_wing = put_wing = lower_spread = upper_spread = None

    # High IV + neutral → sell vol
    if high_iv and stance == "中性":
        if call_wing and put_wing and atm_k:
            add(
                "sell_strangle",
                "卖出宽跨式",
                f"IV 分位偏高（{pct}%）且方向中性，卖虚值 Call/Put 收取权利金；"
                f"需保证金与严格止损。",
                [
                    {"side": "S", "type": "C", "strike": call_wing},
                    {"side": "S", "type": "P", "strike": put_wing},
                ],
                score=0.85 if rising else 0.75,
                risk="高",
            )
            add(
                "iron_condor",
                "铁鹰式（宽）",
                "高 IV 环境下用价差限制裸卖风险，适合震荡市。",
                [
                    {"side": "S", "type": "C", "strike": call_wing},
                    {"side": "B", "type": "C", "strike": _round_strike(call_wing * 1.03)},
                    {"side": "S", "type": "P", "strike": put_wing},
                    {"side": "B", "type": "P", "strike": _round_strike(put_wing * 0.97)},
                ],
                score=0.7,
                risk="中",
            )
        else:
            add(
                "sell_straddle",
                "卖出跨式（ATM）",
                "IV 偏高且方向不明，可考虑 ATM 卖跨收溢价（风险极高，需专业风控）。",
                [{"side": "S", "type": "C", "strike": atm_k}, {"side": "S", "type": "P", "strike": atm_k}]
                if atm_k
                else [],
                score=0.65,
                risk="极高",
            )

    # Low IV + expecting move
    if low_iv and (rising or stance != "中性"):
        if atm_k:
            add(
                "buy_straddle",
                "买入跨式",
                f"IV 分位偏低（{pct}%）且波动升温，买 ATM 跨式博弈方向突破。",
                [
                    {"side": "B", "type": "C", "strike": atm_k},
                    {"side": "B", "type": "P", "strike": atm_k},
                ],
                score=0.72,
                risk="中",
            )

    # Directional with ladder edge
    best_call = None
    best_put = None
    best_call_edge = -999.0
    best_put_edge = -999.0
    for r in rows:
        edge = r.get("edge_expiry")
        if edge is None:
            continue
        m = float(r.get("moneyness_pct") or 0)
        if m >= 0 and float(edge) > best_call_edge:
            best_call_edge = float(edge)
            best_call = r
        if m <= 0 and float(edge) > best_put_edge:
            best_put_edge = float(edge)
            best_put = r

    if stance == "看涨" and not high_iv:
        if best_call and best_call_edge >= 0.02:
            add(
                "buy_call",
                f"买入 {best_call.get('strike')} Call",
                f"现货偏多且模型到期 ITM 概率高于隐含约 {best_call_edge * 100:.1f}pp。",
                [{"side": "B", "type": "C", "strike": best_call.get("strike"), "symbol": best_call.get("symbol")}],
                score=0.8,
                risk="中",
            )
        elif lower_spread and upper_spread:
            add(
                "bull_call_spread",
                "牛市看涨价差",
                "方向偏多且 IV 未极端，用价差降低权利金成本。",
                [
                    {"side": "B", "type": "C", "strike": lower_spread},
                    {"side": "S", "type": "C", "strike": upper_spread},
                ],
                score=0.68,
                risk="中",
            )

    if stance == "看跌":
        if best_put and best_put_edge >= 0.02:
            add(
                "buy_put",
                f"买入 {best_put.get('strike')} Put",
                f"现货偏空且 Put 侧模型概率相对隐含有优势约 {best_put_edge * 100:.1f}pp。",
                [{"side": "B", "type": "P", "strike": best_put.get("strike"), "symbol": best_put.get("symbol")}],
                score=0.78,
                risk="中",
            )
        elif high_iv and put_wing:
            add(
                "bear_put_spread",
                "熊市看跌价差",
                "偏空且 IV 偏高，买入 ATM Put 同时卖出虚值 Put 降成本。",
                [
                    {"side": "B", "type": "P", "strike": atm_k},
                    {"side": "S", "type": "P", "strike": put_wing},
                ],
                score=0.66,
                risk="中",
            )

    if high_iv and stance == "看涨":
        add(
            "wait",
            "谨慎追涨期权",
            "方向偏多但 IV 溢价高，优先现货/永续；若买 Call 选较短 DTE 并限仓。",
            [],
            score=0.55,
            risk="中",
        )

    if falling and high_iv:
        add(
            "sell_strangle",
            "IV 回落中卖波动",
            f"IV 分位仍高但 24h 回落 {chg:+.1f}%，可关注卖 vol 窗口（设止损）。",
            [
                {"side": "S", "type": "C", "strike": call_wing},
                {"side": "S", "type": "P", "strike": put_wing},
            ]
            if call_wing and put_wing
            else [],
            score=0.62,
            risk="高",
        )

    cmp = venue_compare or {}
    aligned = cmp.get("aligned") if isinstance(cmp, dict) else None
    comparison = None
    if isinstance(aligned, dict) and aligned.get("available"):
        comparison = aligned.get("comparison")
        expiry_note = aligned.get("expiry_date") or ""
    else:
        comparison = cmp.get("comparison") if isinstance(cmp, dict) else None
        expiry_note = ""
    if isinstance(comparison, dict) and comparison.get("iv_spread_pp") is not None:
        spread = float(comparison.get("iv_spread_pp") or 0)
        if abs(spread) >= 2.5:
            cheaper = "Deribit" if spread > 0 else "Binance"
            when = f"同到期 {expiry_note} " if expiry_note else ""
            add(
                "buy_straddle" if low_iv else "sell_strangle",
                "跨所 IV 套利观察",
                f"{when}Binance 较 Deribit {spread:+.1f}pp；买方期权可优先 {cheaper}，"
                f"卖 vol 可在偏高交易所对冲（需计流动性与合约规格）。",
                [],
                score=0.62 if expiry_note else 0.58,
                risk="中",
            )

    if not strategies:
        add(
            "wait",
            "维持观望",
            f"{base} 当前 IV 与方向未形成鲜明策略边际，宜轻仓或等待结构明朗。",
            [],
            score=0.4,
            risk="低",
        )

    strategies.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return strategies[:4]


# strategy_pack.kind -> options overlay backtest structure
OVERLAY_BY_STRATEGY_KIND: dict[str, str | None] = {
    "buy_call": "call_overlay",
    "bull_call_spread": "call_overlay",
    "buy_put": "put_hedge",
    "bear_put_spread": "put_hedge",
    "sell_straddle": "short_straddle_iv",
    "sell_strangle": "short_straddle_iv",
    "iron_condor": "short_straddle_iv",
    "buy_straddle": "long_straddle",
    "wait": None,
}


def resolve_overlay_from_strategy_pack(
    pack: dict[str, Any] | None,
) -> dict[str, Any]:
    """Map top strategy_pack entry to an options backtest overlay id."""
    pack = pack or {}
    strategies = pack.get("strategies") or []
    if not strategies:
        return {
            "overlay_id": None,
            "skip_reason": "strategy_pack 为空",
            "headline": pack.get("headline"),
        }
    top = strategies[0]
    kind = str(top.get("id") or "")
    overlay_id = OVERLAY_BY_STRATEGY_KIND.get(kind)
    base = {
        "strategy_kind": kind,
        "strategy_name": top.get("name"),
        "score": top.get("score"),
        "rationale": top.get("rationale"),
        "headline": pack.get("headline"),
        "alternates": [
            {
                "kind": s.get("id"),
                "name": s.get("name"),
                "overlay": OVERLAY_BY_STRATEGY_KIND.get(str(s.get("id") or "")),
            }
            for s in strategies[1:4]
        ],
    }
    if overlay_id is None:
        return {
            **base,
            "overlay_id": None,
            "skip_reason": f"「{top.get('name')}」不适合叠加回测，建议观望",
        }
    return {**base, "overlay_id": overlay_id}


def build_strategy_pack(
    *,
    scan_item: dict[str, Any] | None = None,
    strike_report: dict[str, Any] | None = None,
    spot_stance: str = "中性",
    venue_compare: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spot = None
    if strike_report:
        spot = strike_report.get("spot")
    elif scan_item:
        spot = scan_item.get("underlying_price")
    strategies = suggest_strategies(
        scan_item=scan_item,
        strike_report=strike_report,
        spot_stance=spot_stance,
        spot=spot,
        venue_compare=venue_compare,
    )
    headline = strategies[0]["name"] if strategies else "观望"
    return {
        "headline": headline,
        "strategies": strategies,
        "disclaimer": _DISCLAIMER,
    }
