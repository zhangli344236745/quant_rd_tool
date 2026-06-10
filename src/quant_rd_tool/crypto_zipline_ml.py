"""Walk-forward XGBoost strategies for crypto zipline lab."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb

from quant_rd_tool.crypto_zipline_ml_features import (
    build_ml_feature_frame,
    forward_return_labels,
)
from quant_rd_tool.crypto_zipline_pandas import run_bar_backtest
from quant_rd_tool.crypto_zipline_strategies import signals as sig
from quant_rd_tool.crypto_zipline_strategies.tv_catalog import get_tv_strategy
from quant_rd_tool.crypto_zipline_timeframes import effective_ml_train_bars


def compute_walk_forward_targets(
    df: pd.DataFrame,
    params: dict[str, Any],
    *,
    timeframe: str = "15m",
    include_tv: bool = True,
) -> tuple[pd.Series, dict[str, Any]]:
    train_bars = effective_ml_train_bars(timeframe, int(params.get("train_bars", 2000)))
    retrain_every = int(params.get("retrain_every", 500))
    label_horizon = int(params.get("label_horizon", 1))
    min_train = int(params.get("min_train_samples", 500))

    features = build_ml_feature_frame(df, include_tv=include_tv)
    labels = forward_return_labels(df["close"].astype(float), horizon=label_horizon)
    n = len(df)
    targets = pd.Series(0.0, index=df.index)
    last_model: xgb.XGBRegressor | None = None
    last_metrics: dict[str, Any] = {}

    for t in range(n):
        if t < train_bars:
            continue
        if (t - train_bars) % retrain_every == 0 or last_model is None:
            train_start = max(0, t - train_bars)
            x_train = features.iloc[train_start:t].values
            y_train = labels.iloc[train_start:t].values
            mask = ~(np.isnan(x_train).any(axis=1) | np.isnan(y_train))
            x_clean = x_train[mask]
            y_clean = y_train[mask]
            if len(x_clean) < min_train:
                continue
            model = xgb.XGBRegressor(
                n_estimators=80,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                objective="reg:squarederror",
                n_jobs=1,
                verbosity=0,
            )
            model.fit(x_clean, y_clean)
            last_model = model
            pred = model.predict(x_clean)
            ic = float(np.corrcoef(pred, y_clean)[0, 1]) if len(y_clean) > 10 else None
            direction = float((np.sign(pred) == np.sign(y_clean)).mean()) if len(y_clean) > 10 else None
            last_metrics = {
                "ic": round(ic, 6) if ic is not None and not np.isnan(ic) else None,
                "direction_accuracy": round(direction, 4) if direction is not None else None,
                "train_samples": int(len(x_clean)),
            }

        if last_model is None:
            continue
        x_row = features.iloc[t : t + 1].values
        if np.isnan(x_row).any():
            continue
        pred = float(last_model.predict(x_row)[0])
        targets.iloc[t] = 1.0 if pred > float(params.get("xgb_threshold", 0.0)) else 0.0

    return targets, last_metrics


def _base_tv_targets(df: pd.DataFrame, base_strategy: str, params: dict[str, Any]) -> pd.Series:
    spec = get_tv_strategy(base_strategy)
    merged = {**(spec["default_params"] if spec else {}), **params}
    n = len(df)
    targets = [0.0] * n
    closes: list[float] = []
    volumes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    opens: list[float] = []
    last_target = 0.0
    vols = df["volume"].tolist() if "volume" in df.columns else [0.0] * n
    for i in range(n):
        closes.append(float(df["close"].iloc[i]))
        volumes.append(float(vols[i]))
        highs.append(float(df["high"].iloc[i]) if "high" in df.columns else closes[-1])
        lows.append(float(df["low"].iloc[i]) if "low" in df.columns else closes[-1])
        opens.append(float(df["open"].iloc[i]) if "open" in df.columns else closes[max(0, i - 1)])
        t = sig.signal_for_strategy(
            base_strategy,
            closes,
            volumes,
            merged,
            highs=highs,
            lows=lows,
            opens=opens,
            last_target=last_target,
        )
        if t is not None:
            last_target = t
        targets[i] = last_target
    return pd.Series(targets, index=df.index)


def compute_ml_targets(
    df: pd.DataFrame,
    *,
    strategy_id: str,
    params: dict[str, Any],
    timeframe: str = "15m",
) -> tuple[pd.Series, dict[str, Any], int]:
    """Walk-forward ML target series for pandas or zipline backtests."""
    if strategy_id == "xgb_alpha158":
        targets, ml_metrics = compute_walk_forward_targets(
            df, params, timeframe=timeframe, include_tv=False
        )
        warmup = effective_ml_train_bars(timeframe, int(params.get("train_bars", 2000))) + 5
    elif strategy_id == "xgb_tv_ensemble":
        targets, ml_metrics = compute_walk_forward_targets(
            df, params, timeframe=timeframe, include_tv=True
        )
        warmup = effective_ml_train_bars(timeframe, int(params.get("train_bars", 2000))) + 5
    elif strategy_id == "xgb_tv_filter":
        base = str(params.get("base_strategy", "supertrend"))
        base_params = {k: v for k, v in params.items() if k != "base_strategy"}
        tv_targets = _base_tv_targets(df, base, base_params)
        xgb_targets, ml_metrics = compute_walk_forward_targets(
            df, params, timeframe=timeframe, include_tv=False
        )
        targets = ((tv_targets > 0.5) & (xgb_targets > 0.5)).astype(float)
        ml_metrics = {**ml_metrics, "base_strategy": base}
        warmup = effective_ml_train_bars(timeframe, int(params.get("train_bars", 2000))) + 5
    else:
        raise ValueError(f"Unknown ML strategy: {strategy_id}")
    return targets.fillna(0.0).astype(float), ml_metrics, warmup


def bar_epoch_ms(df: pd.DataFrame) -> pd.Series:
    if "timestamp" in df.columns:
        return df["timestamp"].astype("int64")
    return (pd.to_datetime(df["date"], utc=True).astype("int64") // 10**6).astype("int64")


def build_target_lookup(df: pd.DataFrame, targets: pd.Series) -> dict[int, float]:
    """Map bar epoch-ms → target for zipline handle_data lookup."""
    ms = bar_epoch_ms(df)
    lookup: dict[int, float] = {}
    for i, t_ms in enumerate(ms):
        lookup[int(t_ms)] = float(targets.iloc[i])
    return lookup


def run_ml_strategy(
    df: pd.DataFrame,
    *,
    strategy_id: str,
    params: dict[str, Any],
    capital_base: float,
    timeframe: str = "15m",
) -> dict[str, Any]:
    targets, ml_metrics, warmup = compute_ml_targets(
        df, strategy_id=strategy_id, params=params, timeframe=timeframe
    )
    work = df.copy()
    work["target"] = targets
    out = run_bar_backtest(work, capital_base=capital_base, warmup=warmup)
    out["ml_metrics"] = ml_metrics
    out["strategy_id"] = strategy_id
    return out
