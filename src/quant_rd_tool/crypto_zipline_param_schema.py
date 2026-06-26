"""Optuna parameter schemas for crypto zipline single-strategy tuning."""

from __future__ import annotations

from typing import Any

import optuna

from quant_rd_tool.crypto_zipline_strategies import get_strategy

TUNABLE_STRATEGY_IDS: tuple[str, ...] = (
    "ma_crossover",
    "ema_trend",
    "momentum_rsi",
    "bollinger_revert",
    "macd_cross",
    "supertrend",
    "donchian_breakout",
    "ema_rsi_filter",
    "adx_trend",
    "stoch_rsi",
    "volume_breakout",
    "bb_squeeze",
    "macd_rsi_confirm",
)

_PARAM_SCHEMAS: dict[str, list[dict[str, Any]]] = {
    "ma_crossover": [
        {"name": "fast", "type": "int", "min": 2, "max": 60, "default": 10, "label": "快线"},
        {"name": "slow", "type": "int", "min": 5, "max": 120, "default": 30, "label": "慢线"},
    ],
    "ema_trend": [
        {"name": "fast", "type": "int", "min": 2, "max": 60, "default": 12, "label": "快线"},
        {"name": "slow", "type": "int", "min": 5, "max": 120, "default": 26, "label": "慢线"},
    ],
    "momentum_rsi": [
        {"name": "period", "type": "int", "min": 5, "max": 40, "default": 14, "label": "RSI 周期"},
        {"name": "oversold", "type": "float", "min": 10, "max": 45, "default": 30, "label": "超卖"},
        {"name": "overbought", "type": "float", "min": 55, "max": 90, "default": 70, "label": "超买"},
    ],
    "bollinger_revert": [
        {"name": "period", "type": "int", "min": 10, "max": 60, "default": 20, "label": "周期"},
        {"name": "std_mult", "type": "float", "min": 1.0, "max": 3.5, "default": 2.0, "label": "标准差"},
    ],
    "macd_cross": [
        {"name": "fast", "type": "int", "min": 5, "max": 30, "default": 12, "label": "快线"},
        {"name": "slow", "type": "int", "min": 10, "max": 60, "default": 26, "label": "慢线"},
        {"name": "signal", "type": "int", "min": 3, "max": 20, "default": 9, "label": "信号线"},
    ],
    "supertrend": [
        {"name": "atr_len", "type": "int", "min": 5, "max": 30, "default": 10, "label": "ATR 周期"},
        {"name": "factor", "type": "float", "min": 1.5, "max": 5.0, "default": 3.0, "label": "倍数"},
    ],
    "donchian_breakout": [
        {"name": "channel", "type": "int", "min": 5, "max": 80, "default": 20, "label": "通道周期"},
    ],
    "ema_rsi_filter": [
        {"name": "fast", "type": "int", "min": 2, "max": 40, "default": 12, "label": "EMA 快"},
        {"name": "slow", "type": "int", "min": 10, "max": 80, "default": 26, "label": "EMA 慢"},
        {"name": "rsi_period", "type": "int", "min": 5, "max": 40, "default": 14, "label": "RSI 周期"},
        {"name": "rsi_min", "type": "float", "min": 25, "max": 55, "default": 45, "label": "RSI 下限"},
        {"name": "rsi_max", "type": "float", "min": 60, "max": 90, "default": 75, "label": "RSI 上限"},
    ],
    "adx_trend": [
        {"name": "period", "type": "int", "min": 7, "max": 30, "default": 14, "label": "ADX 周期"},
        {"name": "adx_threshold", "type": "float", "min": 15, "max": 40, "default": 25, "label": "ADX 阈值"},
    ],
    "stoch_rsi": [
        {"name": "rsi_period", "type": "int", "min": 5, "max": 30, "default": 14, "label": "RSI 周期"},
        {"name": "stoch_period", "type": "int", "min": 5, "max": 30, "default": 14, "label": "Stoch 周期"},
        {"name": "oversold", "type": "float", "min": 10, "max": 35, "default": 20, "label": "超卖"},
        {"name": "overbought", "type": "float", "min": 65, "max": 90, "default": 80, "label": "超买"},
    ],
    "volume_breakout": [
        {"name": "lookback", "type": "int", "min": 5, "max": 60, "default": 20, "label": "回看"},
        {"name": "vol_mult", "type": "float", "min": 1.0, "max": 4.0, "default": 1.5, "label": "放量倍数"},
    ],
    "bb_squeeze": [
        {"name": "bb_period", "type": "int", "min": 10, "max": 40, "default": 20, "label": "BB 周期"},
        {"name": "bb_std", "type": "float", "min": 1.0, "max": 3.0, "default": 2.0, "label": "BB 标准差"},
        {"name": "squeeze_lookback", "type": "int", "min": 40, "max": 200, "default": 120, "label": "压缩回看"},
        {"name": "bw_percentile", "type": "float", "min": 5, "max": 40, "default": 20, "label": "带宽分位"},
    ],
    "macd_rsi_confirm": [
        {"name": "fast", "type": "int", "min": 5, "max": 30, "default": 12, "label": "MACD 快"},
        {"name": "slow", "type": "int", "min": 10, "max": 60, "default": 26, "label": "MACD 慢"},
        {"name": "signal", "type": "int", "min": 3, "max": 20, "default": 9, "label": "信号线"},
        {"name": "rsi_period", "type": "int", "min": 5, "max": 40, "default": 14, "label": "RSI 周期"},
        {"name": "rsi_floor", "type": "float", "min": 35, "max": 60, "default": 50, "label": "RSI 下限"},
        {"name": "rsi_cap", "type": "float", "min": 60, "max": 85, "default": 70, "label": "RSI 上限"},
    ],
}


def list_tunable_strategies() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sid in TUNABLE_STRATEGY_IDS:
        spec = get_strategy(sid)
        if not spec:
            continue
        out.append(
            {
                "id": sid,
                "name": spec["name"],
                "description": spec["description"],
                "min_bars": spec["min_bars"],
                "default_params": dict(spec["default_params"]),
                "param_schema": get_param_schema(sid),
            }
        )
    return out


def get_param_schema(strategy_id: str) -> list[dict[str, Any]]:
    sid = strategy_id.strip()
    if sid not in _PARAM_SCHEMAS:
        raise ValueError(f"strategy not tunable: {strategy_id}")
    return list(_PARAM_SCHEMAS[sid])


def suggest_params(trial: optuna.Trial, strategy_id: str) -> dict[str, Any]:
    schema = get_param_schema(strategy_id)
    raw: dict[str, Any] = {}
    for p in schema:
        name = p["name"]
        if p["type"] == "int":
            raw[name] = trial.suggest_int(name, int(p["min"]), int(p["max"]))
        else:
            raw[name] = trial.suggest_float(name, float(p["min"]), float(p["max"]))
    return validate_params(strategy_id, raw)


def validate_params(strategy_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    sid = strategy_id.strip()
    spec = get_strategy(sid)
    if not spec:
        raise ValueError(f"unknown strategy: {strategy_id}")
    if sid not in _PARAM_SCHEMAS:
        raise ValueError(f"strategy not tunable: {strategy_id}")

    merged = {**spec["default_params"], **(params or {})}
    for p in _PARAM_SCHEMAS[sid]:
        key = p["name"]
        if p["type"] == "int":
            merged[key] = int(merged[key])
        else:
            merged[key] = float(merged[key])

    if sid in {"ma_crossover", "ema_trend", "ema_rsi_filter", "macd_cross", "macd_rsi_confirm"}:
        if int(merged["fast"]) >= int(merged["slow"]):
            raise ValueError("fast must be < slow")
    if sid == "ema_rsi_filter" and float(merged["rsi_min"]) >= float(merged["rsi_max"]):
        raise ValueError("rsi_min must be < rsi_max")
    if sid == "macd_rsi_confirm" and float(merged["rsi_floor"]) >= float(merged["rsi_cap"]):
        raise ValueError("rsi_floor must be < rsi_cap")
    if sid == "momentum_rsi" and float(merged["oversold"]) >= float(merged["overbought"]):
        raise ValueError("oversold must be < overbought")
    if sid == "stoch_rsi" and float(merged["oversold"]) >= float(merged["overbought"]):
        raise ValueError("oversold must be < overbought")
    if sid == "stoch_rsi":
        merged.setdefault("k_smooth", 3)
        merged.setdefault("d_smooth", 3)

    return merged
