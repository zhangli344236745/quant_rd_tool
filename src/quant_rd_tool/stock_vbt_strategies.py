"""VectorBT-based A-share strategy templates (signals only; execution via ashare pandas)."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import vectorbt as vbt

StrategyFn = Callable[[pd.DataFrame, dict[str, Any]], tuple[pd.Series, pd.Series]]


def _require_ohlcv(df: pd.DataFrame) -> pd.Series:
    if "close" not in df.columns:
        raise ValueError("dataframe must include close column")
    return df["close"].astype(float)


def _signals_to_target(entries: pd.Series, exits: pd.Series) -> pd.Series:
    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)
    target: list[float] = []
    pos = 0.0
    for ent, ex in zip(entries, exits, strict=True):
        if ent:
            pos = 1.0
        elif ex:
            pos = 0.0
        target.append(pos)
    return pd.Series(target, index=entries.index, dtype=float)


def _sma_cross(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    close = _require_ohlcv(df)
    fast = int(params["fast"])
    slow = int(params["slow"])
    if fast >= slow:
        raise ValueError("fast must be < slow")
    fast_ma = vbt.MA.run(close, window=fast).ma
    slow_ma = vbt.MA.run(close, window=slow).ma
    entries = fast_ma.vbt.crossed_above(slow_ma)
    exits = fast_ma.vbt.crossed_below(slow_ma)
    return entries, exits


def _rsi_revert(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    close = _require_ohlcv(df)
    period = int(params["period"])
    oversold = float(params["oversold"])
    overbought = float(params["overbought"])
    rsi = vbt.RSI.run(close, window=period).rsi
    entries = (rsi < oversold) & (rsi.shift(1) >= oversold)
    exits = (rsi > overbought) & (rsi.shift(1) <= overbought)
    return entries.fillna(False), exits.fillna(False)


def _macd_cross(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    close = _require_ohlcv(df)
    macd = vbt.MACD.run(
        close,
        fast_window=int(params["fast"]),
        slow_window=int(params["slow"]),
        signal_window=int(params["signal"]),
    )
    entries = macd.macd.vbt.crossed_above(macd.signal)
    exits = macd.macd.vbt.crossed_below(macd.signal)
    return entries, exits


def _bb_breakout(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    close = _require_ohlcv(df)
    period = int(params["period"])
    std = float(params["std"])
    bb = vbt.BBANDS.run(close, window=period, alpha=std)
    entries = close.vbt.crossed_above(bb.upper)
    exits = close.vbt.crossed_below(bb.lower)
    return entries, exits


_STRATEGIES: dict[str, dict[str, Any]] = {
    "sma_cross": {
        "id": "sma_cross",
        "name": "双均线交叉",
        "description": "快线上穿慢线做多，下穿平仓",
        "min_bars": 35,
        "default_params": {"fast": 10, "slow": 30},
        "param_schema": [
            {"name": "fast", "type": "int", "min": 2, "max": 120, "default": 10, "label": "快线周期"},
            {"name": "slow", "type": "int", "min": 5, "max": 250, "default": 30, "label": "慢线周期"},
        ],
        "runner": _sma_cross,
    },
    "rsi_revert": {
        "id": "rsi_revert",
        "name": "RSI 超买超卖",
        "description": "RSI 超卖买入，超买平仓",
        "min_bars": 20,
        "default_params": {"period": 14, "oversold": 30, "overbought": 70},
        "param_schema": [
            {"name": "period", "type": "int", "min": 5, "max": 60, "default": 14, "label": "RSI 周期"},
            {"name": "oversold", "type": "float", "min": 5, "max": 45, "default": 30, "label": "超卖线"},
            {"name": "overbought", "type": "float", "min": 55, "max": 95, "default": 70, "label": "超买线"},
        ],
        "runner": _rsi_revert,
    },
    "macd_cross": {
        "id": "macd_cross",
        "name": "MACD 金叉",
        "description": "MACD 上穿信号线做多，下穿平仓",
        "min_bars": 40,
        "default_params": {"fast": 12, "slow": 26, "signal": 9},
        "param_schema": [
            {"name": "fast", "type": "int", "min": 5, "max": 30, "default": 12, "label": "快线"},
            {"name": "slow", "type": "int", "min": 10, "max": 60, "default": 26, "label": "慢线"},
            {"name": "signal", "type": "int", "min": 3, "max": 20, "default": 9, "label": "信号线"},
        ],
        "runner": _macd_cross,
    },
    "bb_breakout": {
        "id": "bb_breakout",
        "name": "布林带突破",
        "description": "突破上轨做多，跌破下轨平仓",
        "min_bars": 25,
        "default_params": {"period": 20, "std": 2.0},
        "param_schema": [
            {"name": "period", "type": "int", "min": 10, "max": 60, "default": 20, "label": "周期"},
            {"name": "std", "type": "float", "min": 1.0, "max": 4.0, "default": 2.0, "label": "标准差倍数"},
        ],
        "runner": _bb_breakout,
    },
}


def list_strategies() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in _STRATEGIES.values():
        out.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "description": spec["description"],
                "min_bars": spec["min_bars"],
                "default_params": dict(spec["default_params"]),
                "param_schema": spec["param_schema"],
            }
        )
    return out


def get_strategy(strategy_id: str) -> dict[str, Any]:
    sid = strategy_id.strip()
    if sid not in _STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy_id}")
    spec = _STRATEGIES[sid]
    return {
        "id": spec["id"],
        "name": spec["name"],
        "description": spec["description"],
        "min_bars": spec["min_bars"],
        "default_params": dict(spec["default_params"]),
        "param_schema": spec["param_schema"],
    }


def _merge_params(strategy_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    spec = _STRATEGIES[strategy_id]
    merged = {**spec["default_params"], **(params or {})}
    if strategy_id == "sma_cross" and int(merged["fast"]) >= int(merged["slow"]):
        raise ValueError("fast must be < slow")
    return merged


def build_target_series(
    df: pd.DataFrame,
    strategy_id: str,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    sid = strategy_id.strip()
    if sid not in _STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy_id}")
    spec = _STRATEGIES[sid]
    merged = _merge_params(sid, params)
    work = df.copy()
    if work.index.name == "date" or isinstance(work.index, pd.DatetimeIndex):
        if "date" not in work.columns:
            work = work.reset_index()
    entries, exits = spec["runner"](work, merged)
    work["target"] = _signals_to_target(entries, exits)
    return work


def validate_params(strategy_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    return _merge_params(strategy_id.strip(), params)
