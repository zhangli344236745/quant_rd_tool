"""Metrics extraction for A-share VBT lab (pandas/numpy only, no charts)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _safe_float(val: Any) -> float | None:
    try:
        if val is None:
            return None
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def equity_to_returns(equity_curve: list[dict[str, Any]]) -> pd.Series:
    if len(equity_curve) < 2:
        raise ValueError("equity curve too short for returns")
    rows: list[tuple[pd.Timestamp, float]] = []
    for pt in equity_curve:
        ts = pd.Timestamp(pt.get("time") or pt.get("ts") or pt.get("date"))
        val = float(pt["value"])
        rows.append((ts, val))
    s = pd.Series({ts: val for ts, val in rows}).sort_index()
    returns = s.pct_change().dropna()
    returns.index = pd.DatetimeIndex(returns.index)
    returns.name = "strategy"
    return returns


def extract_metrics(returns: pd.Series) -> dict[str, Any]:
    if returns.empty:
        return {"error": "no returns"}

    total_return = float((1.0 + returns).prod() - 1.0)
    n_days = int(len(returns))
    years = n_days / 252.0
    cagr = None
    if years > 0 and (1.0 + total_return) > 0:
        cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0)

    std = float(returns.std(ddof=1)) if n_days > 1 else 0.0
    ann_vol = _safe_float(std * math.sqrt(252)) if std > 0 else 0.0
    sharpe = _safe_float(returns.mean() / std * math.sqrt(252)) if std > 0 else None

    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (
        _safe_float(returns.mean() / downside_std * math.sqrt(252)) if downside_std > 0 else None
    )

    cum = (1.0 + returns).cumprod()
    drawdown = cum / cum.cummax() - 1.0
    max_drawdown = _safe_float(drawdown.min())

    non_zero = returns[returns != 0]
    win_rate = _safe_float((non_zero > 0).mean()) if len(non_zero) else None

    metrics: dict[str, Any] = {
        "total_return": _safe_float(total_return),
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "volatility": ann_vol,
        "win_rate": win_rate,
        "best_day": _safe_float(returns.max()),
        "worst_day": _safe_float(returns.min()),
        "trading_days": n_days,
    }
    return {k: v for k, v in metrics.items() if v is not None or k == "trading_days"}


def build_report_artifacts(
    returns: pd.Series,
    out_dir: Path,
    *,
    title: str = "A-Share VBT Lab",
) -> dict[str, Any]:
    """Persist metrics JSON only."""
    _ = title
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = extract_metrics(returns)
    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"metrics": metrics, "metrics_path": str(metrics_path)}
