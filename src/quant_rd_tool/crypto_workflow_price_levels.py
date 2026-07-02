"""IV-based spot / perp / options price guidance for workflow advice."""

from __future__ import annotations

import math
from typing import Any, Literal

IvSource = Literal["options", "realized", "default"]
MarketType = Literal["spot", "perp", "options"]

_PRICE_DISCLAIMER = (
    "参考价位基于 ATM 隐含波动率与持有周期估算的预期波动带，"
    "未计资金费率、滑点与跳空；不构成交易指令。"
)

_PERP_DISCLAIMER = (
    "永续参考价基于标记价与 IV 波动带，含典型滑点假设；"
    "高杠杆需结合 liquidation 距离与 funding，不构成交易指令。"
)

_OPTIONS_DISCLAIMER = (
    "期权行权价与权利金预算为 IV 结构下的参考模板，"
    "实际报价以交易所盘口为准；不构成交易指令。"
)


def _timeframe_horizon_days(timeframe: str) -> float:
    tf = (timeframe or "1d").strip().lower()
    if tf == "15m":
        return 1.0
    if tf == "1h":
        return 3.0
    if tf == "4h":
        return 7.0
    return 14.0


def _round_price(price: float, spot: float) -> float:
    if spot >= 10_000:
        return round(price, 2)
    if spot >= 100:
        return round(price, 2)
    if spot >= 1:
        return round(price, 4)
    return round(price, 6)


def _round_strike(strike: float, spot: float) -> float:
    if spot >= 10_000:
        step = 1000.0
    elif spot >= 1000:
        step = 500.0
    elif spot >= 100:
        step = 50.0
    elif spot >= 10:
        step = 5.0
    else:
        step = 1.0
    return round(strike / step) * step


def _stance_side(stance: str, action: str) -> str:
    if action == "sell" or stance == "看跌" or "空" in stance:
        return "short"
    if action == "hold" or stance == "中性":
        return "neutral"
    return "long"


def _resolve_iv(
    *,
    atm_iv: float | None,
    annualized_realized_vol: float | None,
) -> tuple[float, IvSource]:
    if atm_iv is not None and atm_iv > 0:
        return float(atm_iv), "options"
    if annualized_realized_vol is not None and annualized_realized_vol > 0:
        return float(annualized_realized_vol), "realized"
    return 0.5, "default"


def compute_iv_price_guidance(
    *,
    spot: float,
    stance: str,
    action: str,
    timeframe: str,
    atm_iv: float | None = None,
    dte_days: float | None = None,
    iv_percentile: float | None = None,
    annualized_realized_vol: float | None = None,
    bollinger: dict[str, float | None] | None = None,
    sl_sigma: float = 1.0,
    tp_sigma: float = 1.5,
    entry_sigma: float = 0.35,
    horizon_days: float | None = None,
) -> dict[str, Any]:
    """
    Derive spot reference entry, stop-loss and take-profit from IV-implied move.

    Uses annualized IV scaled to holding horizon: move = spot * iv * sqrt(T/365).
    """
    if spot <= 0:
        return {"available": False, "reason": "invalid spot", "disclaimer": _PRICE_DISCLAIMER}

    iv_eff, iv_source = _resolve_iv(atm_iv=atm_iv, annualized_realized_vol=annualized_realized_vol)
    horizon = float(horizon_days or dte_days or _timeframe_horizon_days(timeframe))
    horizon = max(1.0, min(horizon, 60.0))

    sl_mult = max(0.5, float(sl_sigma))
    tp_mult = max(0.5, float(tp_sigma))
    entry_mult = max(0.0, min(float(entry_sigma), 1.0))

    if iv_percentile is not None:
        if iv_percentile >= 80:
            sl_mult *= 1.25
            tp_mult *= 1.25
        elif iv_percentile <= 20:
            sl_mult *= 0.85
            tp_mult *= 0.85

    expected_move = spot * iv_eff * math.sqrt(horizon / 365.0)
    if expected_move <= 0:
        return {"available": False, "reason": "zero expected move", "disclaimer": _PRICE_DISCLAIMER}

    bb_lower = (bollinger or {}).get("lower")
    bb_upper = (bollinger or {}).get("upper")

    side = "long"
    if action == "sell" or stance == "看跌":
        side = "short"
    elif action == "hold" or stance == "中性":
        side = "neutral"

    if side == "long":
        entry = spot - entry_mult * expected_move
        if bb_lower and bb_lower < spot:
            entry = min(entry, float(bb_lower) * 1.002)
        stop = entry - sl_mult * expected_move
        take = entry + tp_mult * expected_move
        entry_note = "IV 回踩限价参考（偏多）"
    elif side == "short":
        entry = spot + entry_mult * expected_move
        if bb_upper and bb_upper > spot:
            entry = max(entry, float(bb_upper) * 0.998)
        stop = entry + sl_mult * expected_move
        take = entry - tp_mult * expected_move
        entry_note = "IV 反弹限价参考（偏空）"
    else:
        entry = spot
        stop = spot - sl_mult * expected_move
        take = spot + tp_mult * expected_move
        entry_note = "观望：下方支撑 / 上方阻力参考"

    entry_r = _round_price(entry, spot)
    stop_r = _round_price(stop, spot)
    take_r = _round_price(take, spot)

    return {
        "available": True,
        "market_type": "spot",
        "spot": _round_price(spot, spot),
        "side": side,
        "atm_iv": round(iv_eff, 4),
        "iv_source": iv_source,
        "iv_percentile": iv_percentile,
        "horizon_days": round(horizon, 2),
        "expected_move_usd": round(expected_move, 2),
        "expected_move_pct": round(expected_move / spot, 4),
        "entry_price": entry_r,
        "stop_loss_price": stop_r,
        "take_profit_price": take_r,
        "entry_note": entry_note,
        "stop_loss_pct": round((stop_r - entry_r) / entry_r, 4) if entry_r else None,
        "take_profit_pct": round((take_r - entry_r) / entry_r, 4) if entry_r else None,
        "bollinger_lower": bb_lower,
        "bollinger_upper": bb_upper,
        "disclaimer": _PRICE_DISCLAIMER,
    }


def compute_perp_price_guidance(
    *,
    spot: float,
    perp_mark: float | None = None,
    stance: str,
    action: str,
    timeframe: str,
    atm_iv: float | None = None,
    dte_days: float | None = None,
    iv_percentile: float | None = None,
    annualized_realized_vol: float | None = None,
    bollinger: dict[str, float | None] | None = None,
    sl_sigma: float = 1.0,
    tp_sigma: float = 1.5,
    entry_sigma: float = 0.35,
    horizon_days: float | None = None,
    var_ratio: float | None = None,
    var_gate_pct: float = 0.08,
    perp_slippage_pct: float = 0.0003,
) -> dict[str, Any]:
    """Perpetual-specific entry / stop / take-profit on mark price."""
    mark = float(perp_mark) if perp_mark and perp_mark > 0 else float(spot)
    if spot <= 0 or mark <= 0:
        return {"available": False, "market_type": "perp", "reason": "invalid mark", "disclaimer": _PERP_DISCLAIMER}

    basis_bps = (mark / spot - 1.0) * 10_000 if spot > 0 else 0.0
    sl_adj = float(sl_sigma)
    if var_ratio is not None and var_ratio > var_gate_pct:
        sl_adj *= 0.85
    if var_ratio is not None and var_ratio > var_gate_pct * 1.5:
        sl_adj *= 0.85

    base = compute_iv_price_guidance(
        spot=mark,
        stance=stance,
        action=action,
        timeframe=timeframe,
        atm_iv=atm_iv,
        dte_days=dte_days,
        iv_percentile=iv_percentile,
        annualized_realized_vol=annualized_realized_vol,
        bollinger=bollinger,
        sl_sigma=sl_adj,
        tp_sigma=tp_sigma,
        entry_sigma=entry_sigma,
        horizon_days=horizon_days,
    )
    if not base.get("available"):
        return {**base, "market_type": "perp", "disclaimer": _PERP_DISCLAIMER}

    side = str(base.get("side") or "neutral")
    slip = max(0.0, perp_slippage_pct)
    entry = float(base["entry_price"])
    stop = float(base["stop_loss_price"])
    take = float(base["take_profit_price"])
    if side == "long":
        entry = entry * (1 + slip)
        stop = stop * (1 - slip)
        take = take * (1 - slip)
        entry_note = "永续做多限价参考（标记价 + IV 回踩）"
    elif side == "short":
        entry = entry * (1 - slip)
        stop = stop * (1 + slip)
        take = take * (1 + slip)
        entry_note = "永续做空限价参考（标记价 + IV 反弹）"
    else:
        entry_note = "永续观望：上下边界参考（标记价 ± IV 带）"

    entry_r = _round_price(entry, mark)
    stop_r = _round_price(stop, mark)
    take_r = _round_price(take, mark)
    liq_hint = None
    if side == "long" and entry_r:
        liq_hint = f"参考强平距离：标记价跌至 {stop_r} 附近需关注保证金（非精确强平价）"
    elif side == "short" and entry_r:
        liq_hint = f"参考强平距离：标记价涨至 {stop_r} 附近需关注保证金（非精确强平价）"

    return {
        **base,
        "market_type": "perp",
        "spot_index": _round_price(spot, spot),
        "perp_mark": _round_price(mark, spot),
        "basis_bps": round(basis_bps, 2),
        "entry_price": entry_r,
        "stop_loss_price": stop_r,
        "take_profit_price": take_r,
        "entry_note": entry_note,
        "stop_loss_pct": round((stop_r - entry_r) / entry_r, 4) if entry_r else None,
        "take_profit_pct": round((take_r - entry_r) / entry_r, 4) if entry_r else None,
        "var_tightened_stop": bool(var_ratio and var_ratio > var_gate_pct),
        "liquidation_hint": liq_hint,
        "disclaimer": _PERP_DISCLAIMER,
    }


def compute_options_price_guidance(
    *,
    spot: float,
    opt_stance: str,
    spot_stance: str,
    timeframe: str,
    atm_iv: float | None = None,
    atm_strike: float | None = None,
    dte_days: float | None = None,
    iv_percentile: float | None = None,
    annualized_realized_vol: float | None = None,
    strike_ladder: dict[str, Any] | None = None,
    strategy_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Options strike / premium budget / underlying take-profit references."""
    if spot <= 0:
        return {"available": False, "market_type": "options", "reason": "invalid spot", "disclaimer": _OPTIONS_DISCLAIMER}

    iv_eff, iv_source = _resolve_iv(atm_iv=atm_iv, annualized_realized_vol=annualized_realized_vol)
    horizon = float(dte_days or _timeframe_horizon_days(timeframe))
    horizon = max(7.0, min(horizon, 45.0))
    expected_move = spot * iv_eff * math.sqrt(horizon / 365.0)
    if expected_move <= 0:
        return {"available": False, "market_type": "options", "reason": "zero expected move", "disclaimer": _OPTIONS_DISCLAIMER}

    bullish = spot_stance == "看涨" or "多" in opt_stance
    bearish = spot_stance == "看跌" or "空" in opt_stance
    high_vol = iv_percentile is not None and iv_percentile >= 70

    atm_k = float(atm_strike) if atm_strike and atm_strike > 0 else _round_strike(spot, spot)
    ladder_row = None
    if strike_ladder and strike_ladder.get("rows"):
        rows = strike_ladder["rows"]
        if bullish:
            ladder_row = next((r for r in rows if float(r.get("strike") or 0) >= spot), rows[-1])
        elif bearish:
            ladder_row = next((r for r in reversed(rows) if float(r.get("strike") or 0) <= spot), rows[0])
        else:
            ladder_row = min(rows, key=lambda r: abs(float(r.get("strike") or spot) - spot))

    if bullish:
        option_type = "call"
        entry_strike = float(ladder_row["strike"]) if ladder_row else _round_strike(spot, spot)
        alt_strike = _round_strike(spot + 0.5 * expected_move, spot)
        take_profit_spot = _round_price(spot + 1.5 * expected_move, spot)
        stop_loss_spot = _round_price(spot - 1.0 * expected_move, spot)
        entry_note = "买方 Call：近 ATM 行权价参考"
    elif bearish:
        option_type = "put"
        entry_strike = float(ladder_row["strike"]) if ladder_row else _round_strike(spot, spot)
        alt_strike = _round_strike(spot - 0.5 * expected_move, spot)
        take_profit_spot = _round_price(spot - 1.5 * expected_move, spot)
        stop_loss_spot = _round_price(spot + 1.0 * expected_move, spot)
        entry_note = "买方 Put：近 ATM 行权价参考"
    elif high_vol:
        option_type = "straddle"
        entry_strike = atm_k
        alt_strike = _round_strike(spot + expected_move, spot)
        take_profit_spot = _round_price(spot + expected_move, spot)
        stop_loss_spot = _round_price(spot - expected_move, spot)
        entry_note = "高 IV：宽跨/铁鹰模板，行权价以 ATM 为中心"
    else:
        option_type = "watch"
        entry_strike = atm_k
        alt_strike = _round_strike(spot + 0.25 * expected_move, spot)
        take_profit_spot = _round_price(spot + expected_move, spot)
        stop_loss_spot = _round_price(spot - expected_move, spot)
        entry_note = "方向不明：观望或卖出宽跨，ATM 行权价作锚点"

    premium_pct = iv_eff * math.sqrt(horizon / 365.0) * (0.45 if option_type != "straddle" else 0.7)
    premium_budget = spot * premium_pct
    stop_premium_pct = 0.5 if not high_vol else 0.35
    take_premium_pct = 1.0 if not high_vol else 0.6

    strategy_hint = None
    if strategy_pack and strategy_pack.get("strategies"):
        top = strategy_pack["strategies"][0]
        strategy_hint = str(top.get("name") or strategy_pack.get("headline") or "")

    return {
        "available": True,
        "market_type": "options",
        "spot": _round_price(spot, spot),
        "option_type": option_type,
        "entry_strike": _round_strike(entry_strike, spot),
        "alt_strike": _round_strike(alt_strike, spot),
        "expiry_dte": round(horizon, 2),
        "atm_iv": round(iv_eff, 4),
        "iv_source": iv_source,
        "iv_percentile": iv_percentile,
        "expected_move_usd": round(expected_move, 2),
        "expected_move_pct": round(expected_move / spot, 4),
        "premium_budget_usd": round(premium_budget, 2),
        "stop_loss_premium_pct": stop_premium_pct,
        "take_profit_premium_pct": take_premium_pct,
        "stop_loss_spot": stop_loss_spot,
        "take_profit_spot": take_profit_spot,
        "entry_note": entry_note,
        "strategy_hint": strategy_hint,
        "itm_prob": ladder_row.get("itm_prob") if ladder_row else None,
        "disclaimer": _OPTIONS_DISCLAIMER,
    }
