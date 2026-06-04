"""Pandas bar backtest engine (default; works without zipline-reloaded)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def run_bar_backtest(
    df: pd.DataFrame,
    *,
    capital_base: float,
    warmup: int,
    target_col: str = "target",
) -> dict[str, Any]:
    """Simulate target position fraction each bar; long-only 0/1."""
    if df.empty:
        raise ValueError("empty dataframe")

    work = df.reset_index(drop=True)
    cash = float(capital_base)
    shares = 0.0
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    prev_target = 0.0

    for i, row in work.iterrows():
        price = float(row["close"])
        if i < warmup or pd.isna(row.get(target_col)):
            equity = cash + shares * price
            equity_curve.append(_equity_point(row, equity))
            continue

        target = float(row[target_col])
        target = max(0.0, min(1.0, target))
        equity = cash + shares * price
        desired_shares = (equity * target) / price if price > 0 else 0.0
        delta = desired_shares - shares
        if abs(delta) * price > 1e-8:
            cost = delta * price
            cash -= cost
            shares += delta
            side = "buy" if delta > 0 else "sell"
            trades.append(
                {
                    "time": _bar_time(row),
                    "side": side,
                    "price": price,
                    "shares": abs(delta),
                    "value": abs(cost),
                }
            )
        prev_target = target
        equity = cash + shares * price
        equity_curve.append(_equity_point(row, equity))

    equities = [p["value"] for p in equity_curve]
    metrics = _metrics(equities, capital_base, len(trades))
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


def _equity_point(row: pd.Series, value: float) -> dict[str, Any]:
    return {"time": _bar_time(row), "value": round(float(value), 2)}


def _metrics(equities: list[float], capital_base: float, trade_count: int) -> dict[str, Any]:
    if not equities:
        return {"total_return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "trade_count": trade_count}
    start = float(capital_base)
    end = float(equities[-1])
    total_return = (end - start) / start if start else 0.0
    series = pd.Series(equities)
    rets = series.pct_change().dropna()
    sharpe = 0.0
    if len(rets) > 1 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * np.sqrt(len(rets)))
    peak = series.cummax()
    dd = (series - peak) / peak.replace(0, np.nan)
    max_dd = float(dd.min()) if len(dd) else 0.0
    return {
        "total_return": round(total_return, 6),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 6),
        "trade_count": trade_count,
    }
