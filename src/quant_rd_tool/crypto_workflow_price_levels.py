"""IV-based spot entry / stop-loss / take-profit reference levels for workflow advice."""

from __future__ import annotations

import math
from typing import Any, Literal

IvSource = Literal["options", "realized", "default"]

_PRICE_DISCLAIMER = (
    "参考价位基于 ATM 隐含波动率与持有周期估算的预期波动带，"
    "未计资金费率、滑点与跳空；不构成交易指令。"
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
