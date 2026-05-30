from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

Side = Literal["long", "short"]
SizingMode = Literal["leverage_fraction", "atr", "hybrid"]


def compute_sl_tp_prices(*, side: Side, ref_price: float, sl_pct: float, tp_pct: float) -> tuple[float, float]:
    if ref_price <= 0:
        raise ValueError("ref_price must be positive")
    if sl_pct <= 0 or tp_pct <= 0:
        raise ValueError("sl_pct/tp_pct must be positive")
    if side == "long":
        return (round(ref_price * (1 - sl_pct), 10), round(ref_price * (1 + tp_pct), 10))
    return (round(ref_price * (1 + sl_pct), 10), round(ref_price * (1 - tp_pct), 10))


def compute_atr(df, *, period: int = 14) -> float:
    """
    Compute ATR (Average True Range) from an OHLCV-like DataFrame.

    Requires columns: high, low, close
    Returns the latest ATR value.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if df is None or len(df) < 2:
        raise ValueError("need at least 2 rows")
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = tr.combine(tr2, max).combine(tr3, max)
    atr = true_range.rolling(window=period, min_periods=period).mean()
    latest = float(atr.dropna().iloc[-1]) if atr.notna().any() else float(true_range.tail(period).mean())
    return float(latest)


def compute_sl_tp_prices_atr(
    *,
    side: Side,
    ref_price: float,
    atr: float,
    sl_atr: float,
    tp_atr: float,
) -> tuple[float, float]:
    if ref_price <= 0:
        raise ValueError("ref_price must be positive")
    if atr <= 0:
        raise ValueError("atr must be positive")
    if sl_atr <= 0 or tp_atr <= 0:
        raise ValueError("sl_atr/tp_atr must be positive")
    if side == "long":
        return (round(ref_price - sl_atr * atr, 10), round(ref_price + tp_atr * atr, 10))
    return (round(ref_price + sl_atr * atr, 10), round(ref_price - tp_atr * atr, 10))


def _clamp_confidence(confidence: float, *, min_conf: float, max_conf: float) -> float:
    return max(min(float(confidence), max_conf), min_conf)


def compute_notional(
    *,
    free_usdt: float,
    total_risk_fraction: float,
    confidence: float,
    leverage: float = 1.0,
    min_conf: float = 0.0,
    max_conf: float = 1.0,
    max_per_symbol_notional: float | None = None,
) -> float:
    """Legacy leverage-scaled notional: free * risk_fraction * leverage * confidence."""
    if free_usdt <= 0:
        return 0.0
    c = _clamp_confidence(confidence, min_conf=min_conf, max_conf=max_conf)
    notional = float(free_usdt) * float(total_risk_fraction) * float(leverage) * float(c)
    if max_per_symbol_notional is not None:
        notional = min(notional, float(max_per_symbol_notional))
    return max(notional, 0.0)


def compute_notional_atr(
    *,
    free_usdt: float,
    risk_fraction: float,
    confidence: float,
    ref_price: float,
    atr: float,
    sl_atr: float,
    min_conf: float = 0.0,
    max_conf: float = 1.0,
) -> float:
    """
    Size notional so estimated loss to the stop (sl_atr * ATR) ≈ risk budget.

    notional = risk_usdt * ref_price / (sl_atr * atr)
    """
    if free_usdt <= 0 or ref_price <= 0 or atr <= 0 or sl_atr <= 0:
        return 0.0
    c = _clamp_confidence(confidence, min_conf=min_conf, max_conf=max_conf)
    risk_usdt = float(free_usdt) * float(risk_fraction) * float(c)
    stop_distance = float(sl_atr) * float(atr)
    if stop_distance <= 0:
        return 0.0
    return max(risk_usdt * float(ref_price) / stop_distance, 0.0)


def resolve_open_notional(
    *,
    mode: SizingMode,
    free_usdt: float,
    risk_fraction: float,
    confidence: float,
    ref_price: float,
    leverage: float,
    atr: float | None = None,
    sl_atr: float = 1.5,
    min_conf: float = 0.0,
    max_conf: float = 1.0,
    portfolio_cap_usdt: float | None = None,
) -> dict[str, Any]:
    """
    Resolve target open notional (USDT) for one symbol.

    - leverage_fraction: free * risk_fraction * leverage * confidence
    - atr: volatility-scaled from stop distance (sl_atr * ATR)
    - hybrid: min(atr, leverage_fraction cap); falls back to cap if ATR unavailable
    """
    cap = compute_notional(
        free_usdt=free_usdt,
        total_risk_fraction=risk_fraction,
        confidence=confidence,
        leverage=leverage,
        min_conf=min_conf,
        max_conf=max_conf,
    )
    atr_notional: float | None = None
    if atr is not None and atr > 0:
        atr_notional = compute_notional_atr(
            free_usdt=free_usdt,
            risk_fraction=risk_fraction,
            confidence=confidence,
            ref_price=ref_price,
            atr=atr,
            sl_atr=sl_atr,
            min_conf=min_conf,
            max_conf=max_conf,
        )

    if mode == "leverage_fraction":
        notional = cap
    elif mode == "atr":
        notional = atr_notional if atr_notional is not None else 0.0
    else:  # hybrid
        if atr_notional is None:
            notional = cap
        else:
            notional = min(atr_notional, cap) if cap > 0 else atr_notional

    if portfolio_cap_usdt is not None and portfolio_cap_usdt > 0:
        notional = min(notional, float(portfolio_cap_usdt))

    return {
        "mode": mode,
        "notional_usdt": max(float(notional), 0.0),
        "leverage_cap_usdt": cap,
        "atr_notional_usdt": atr_notional,
        "atr": atr,
        "sl_atr": sl_atr,
        "confidence": _clamp_confidence(confidence, min_conf=min_conf, max_conf=max_conf),
        "portfolio_cap_usdt": portfolio_cap_usdt,
    }


@dataclass
class CircuitBreakerState:
    daily_date: str = ""
    daily_start_usdt_total: float = 0.0


def should_block_entries(
    *,
    state: CircuitBreakerState,
    usdt_total: float,
    max_daily_loss_pct: float,
    today: str | None = None,
) -> tuple[bool, CircuitBreakerState, str]:
    """
    Returns (blocked, updated_state, reason).
    Block NEW entries when daily loss exceeds threshold; allow reduceOnly closes.
    """
    if max_daily_loss_pct <= 0:
        return False, state, ""

    d = today or date.today().isoformat()
    st = state
    if st.daily_date != d or st.daily_start_usdt_total <= 0:
        st = CircuitBreakerState(daily_date=d, daily_start_usdt_total=float(usdt_total))
        return False, st, ""

    start = float(st.daily_start_usdt_total)
    if start <= 0:
        return False, st, ""
    loss_pct = max(0.0, (start - float(usdt_total)) / start)
    if loss_pct >= float(max_daily_loss_pct):
        return True, st, f"daily_loss_pct={loss_pct:.2%} >= {max_daily_loss_pct:.2%}"
    return False, st, ""


def apply_circuit_breaker_to_plan(*, plan: dict[str, bool], blocked: bool) -> dict[str, bool]:
    """Block new opens when circuit breaker trips; closes (reduceOnly) remain allowed."""
    if not blocked:
        return plan
    out = dict(plan)
    out["open"] = False
    return out

