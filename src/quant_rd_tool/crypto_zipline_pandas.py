"""Pandas bar backtest engine (default; works without zipline-reloaded)."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

import numpy as np
import pandas as pd

# Default cost model: Binance spot taker ~0.1%, plus modest slippage
DEFAULT_COMMISSION_PCT = 0.001
DEFAULT_SLIPPAGE_PCT = 0.0005

_COST_CTX: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "crypto_backtest_cost_ctx", default=None
)


@contextmanager
def backtest_cost_context(
    *,
    commission_pct: float | None = None,
    slippage_pct: float | None = None,
    bars_per_year: int | None = None,
) -> Iterator[None]:
    """Inject cost/annualization config into nested run_bar_backtest calls."""
    token = _COST_CTX.set(
        {
            "commission_pct": commission_pct,
            "slippage_pct": slippage_pct,
            "bars_per_year": bars_per_year,
        }
    )
    try:
        yield
    finally:
        _COST_CTX.reset(token)


def run_bar_backtest(
    df: pd.DataFrame,
    *,
    capital_base: float,
    warmup: int,
    target_col: str = "target",
    commission_pct: float | None = None,
    slippage_pct: float | None = None,
    bars_per_year: int | None = None,
) -> dict[str, Any]:
    """Simulate target position fraction each bar; long-only 0..1.

    Buys fill at ``price * (1 + slippage)``, sells at ``price * (1 - slippage)``;
    each fill pays ``commission_pct`` of traded value.
    """
    if df.empty:
        raise ValueError("empty dataframe")

    ctx = _COST_CTX.get() or {}
    if commission_pct is None:
        commission_pct = ctx.get("commission_pct")
    if slippage_pct is None:
        slippage_pct = ctx.get("slippage_pct")
    if bars_per_year is None:
        bars_per_year = ctx.get("bars_per_year")
    commission_pct = DEFAULT_COMMISSION_PCT if commission_pct is None else float(commission_pct)
    slippage_pct = DEFAULT_SLIPPAGE_PCT if slippage_pct is None else float(slippage_pct)

    commission_pct = max(0.0, float(commission_pct))
    slippage_pct = max(0.0, float(slippage_pct))

    work = df.reset_index(drop=True)
    cash = float(capital_base)
    shares = 0.0
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    prev_target = 0.0
    total_fees = 0.0
    # Round-trip tracking for win rate / profit factor
    open_cost = 0.0
    round_trips: list[float] = []

    for i, row in work.iterrows():
        price = float(row["close"])
        if i < warmup or pd.isna(row.get(target_col)):
            equity = cash + shares * price
            equity_curve.append(_equity_point(row, equity, target=prev_target))
            continue

        target = float(row[target_col])
        target = max(0.0, min(1.0, target))
        equity = cash + shares * price
        desired_shares = (equity * target) / price if price > 0 else 0.0
        delta = desired_shares - shares
        if abs(delta) * price > 1e-8:
            if delta > 0:
                fill = price * (1.0 + slippage_pct)
            else:
                fill = price * (1.0 - slippage_pct)
            cost = delta * fill
            fee = abs(cost) * commission_pct
            cash -= cost + fee
            total_fees += fee
            side = "buy" if delta > 0 else "sell"
            if delta > 0:
                open_cost += abs(cost) + fee
            else:
                proceeds = abs(cost) - fee
                sold_fraction = min(1.0, abs(delta) / shares) if shares > 0 else 1.0
                basis = open_cost * sold_fraction
                round_trips.append(proceeds - basis)
                open_cost = max(0.0, open_cost - basis)
            shares += delta
            trades.append(
                {
                    "time": _bar_time(row),
                    "side": side,
                    "price": round(fill, 8),
                    "shares": abs(delta),
                    "value": abs(cost),
                    "fee": round(fee, 8),
                }
            )
        prev_target = target
        equity = cash + shares * price
        equity_curve.append(_equity_point(row, equity, target=target))

    closes = work["close"].astype(float)
    equities = [p["value"] for p in equity_curve]
    metrics = _metrics(
        equities,
        capital_base,
        len(trades),
        bars_per_year=bars_per_year,
        round_trips=round_trips,
        total_fees=total_fees,
        closes=closes,
        warmup=warmup,
    )
    final_target = prev_target
    if final_target <= 1e-6:
        position = "flat"
    elif final_target >= 0.95:
        position = "long"
    else:
        position = "partial"
    last_row = work.iloc[-1]
    return {
        "metrics": metrics,
        "trades": trades,
        "equity_curve": equity_curve,
        "cost_model": {
            "commission_pct": commission_pct,
            "slippage_pct": slippage_pct,
            "total_fees": round(total_fees, 2),
        },
        "final_signal": {
            "position": position,
            "target_pct": final_target,
            "bar_time": _bar_time(last_row),
        },
    }


def _bar_time(row: pd.Series) -> str:
    if "date" in row.index and pd.notna(row["date"]):
        return str(row["date"])
    if "timestamp" in row.index and pd.notna(row["timestamp"]):
        ts = pd.to_datetime(int(row["timestamp"]), unit="ms", utc=True)
        return ts.isoformat()
    return ""


def _equity_point(row: pd.Series, value: float, *, target: float | None = None) -> dict[str, Any]:
    pt: dict[str, Any] = {"time": _bar_time(row), "value": round(float(value), 2)}
    if target is not None:
        pt["target"] = round(float(target), 4)
    return pt


def _metrics(
    equities: list[float],
    capital_base: float,
    trade_count: int,
    *,
    bars_per_year: int | None = None,
    round_trips: list[float] | None = None,
    total_fees: float = 0.0,
    closes: pd.Series | None = None,
    warmup: int = 0,
) -> dict[str, Any]:
    if not equities:
        return {"total_return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "trade_count": trade_count}
    start = float(capital_base)
    end = float(equities[-1])
    total_return = (end - start) / start if start else 0.0
    series = pd.Series(equities)
    rets = series.pct_change().dropna()

    n_bars = max(1, len(rets))
    ann_factor = float(bars_per_year) if bars_per_year else float(n_bars)
    ann_sqrt = np.sqrt(ann_factor)

    sharpe = 0.0
    if len(rets) > 1 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * ann_sqrt)

    sortino = 0.0
    downside = rets[rets < 0]
    if len(rets) > 1 and len(downside) > 0 and downside.std() > 0:
        sortino = float(rets.mean() / downside.std() * ann_sqrt)

    peak = series.cummax()
    dd = (series - peak) / peak.replace(0, np.nan)
    max_dd = float(dd.min()) if len(dd) else 0.0

    annualized_return = None
    if bars_per_year and n_bars > 0 and start > 0 and end > 0:
        years = n_bars / float(bars_per_year)
        if years > 0:
            annualized_return = float((end / start) ** (1.0 / years) - 1.0)

    calmar = None
    if annualized_return is not None and max_dd < 0:
        calmar = float(annualized_return / abs(max_dd))

    win_rate = None
    profit_factor = None
    rts = round_trips or []
    if rts:
        wins = [x for x in rts if x > 0]
        losses = [x for x in rts if x <= 0]
        win_rate = len(wins) / len(rts)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = float("inf")

    buy_hold_return = None
    excess_vs_hold = None
    if closes is not None and len(closes) > warmup:
        c0 = float(closes.iloc[warmup])
        c1 = float(closes.iloc[-1])
        if c0 > 0:
            buy_hold_return = (c1 - c0) / c0
            excess_vs_hold = total_return - buy_hold_return

    out: dict[str, Any] = {
        "total_return": round(total_return, 6),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown": round(max_dd, 6),
        "trade_count": trade_count,
        "total_fees": round(total_fees, 2),
    }
    if annualized_return is not None:
        out["annualized_return"] = round(annualized_return, 6)
    if calmar is not None:
        out["calmar"] = round(calmar, 4)
    if win_rate is not None:
        out["win_rate"] = round(win_rate, 4)
    if profit_factor is not None:
        out["profit_factor"] = round(profit_factor, 4) if np.isfinite(profit_factor) else None
        if not np.isfinite(profit_factor):
            out["profit_factor_unbounded"] = True
    if buy_hold_return is not None:
        out["buy_hold_return"] = round(buy_hold_return, 6)
        out["excess_vs_hold"] = round(excess_vs_hold or 0.0, 6)
    return out
