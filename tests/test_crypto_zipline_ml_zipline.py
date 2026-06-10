"""Zipline engine integration for ML strategies."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_rd_tool.crypto_zipline_ml import build_target_lookup, compute_ml_targets
from quant_rd_tool.crypto_zipline_strategies.zipline_algos import _bar_dt_to_epoch_ms


def _synthetic_df(n: int = 1200) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    base_ms = int(pd.Timestamp("2026-01-01", tz="UTC").value // 1_000_000)
    step_ms = 15 * 60 * 1000
    return pd.DataFrame(
        {
            "timestamp": [base_ms + i * step_ms for i in range(n)],
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": rng.uniform(500, 2000, n),
        }
    )


def test_build_target_lookup_roundtrip():
    df = _synthetic_df(50)
    targets = pd.Series([1.0 if i % 2 == 0 else 0.0 for i in range(len(df))])
    lookup = build_target_lookup(df, targets)
    bar_dt = pd.to_datetime(df["timestamp"].iloc[10], unit="ms", utc=True)
    assert lookup[_bar_dt_to_epoch_ms(bar_dt)] == targets.iloc[10]


def test_zipline_algo_uses_precomputed_targets():
    df = _synthetic_df(100)
    params = {"train_bars": 200, "retrain_every": 50, "min_train_samples": 30}
    targets, _, _ = compute_ml_targets(
        df, strategy_id="xgb_alpha158", params=params, timeframe="15m"
    )
    lookup = build_target_lookup(df, targets)
    idx = 80
    bar_dt = pd.to_datetime(df["timestamp"].iloc[idx], unit="ms", utc=True)

    class Ctx:
        pass

    context = Ctx()
    context.target_lookup = lookup
    context.last_bar_dt = bar_dt
    context.last_target = 0.0
    context.strategy_id = "xgb_alpha158"
    context.params = params
    context.combo_spec = None
    context.closes = []
    context.volumes = []
    context.highs = []
    context.lows = []

    from quant_rd_tool.crypto_zipline_strategies import zipline_algos as za

    target = za._compute_target(context)
    assert target == float(targets.iloc[idx])


def test_prepare_ml_zipline_targets():
    df = _synthetic_df(800)
    from quant_rd_tool.crypto_zipline_zipline_engine import _prepare_ml_zipline_targets

    lookup, metrics = _prepare_ml_zipline_targets(
        df,
        strategy_id="xgb_alpha158",
        algo_params={"train_bars": 300, "retrain_every": 100, "min_train_samples": 50},
        timeframe="15m",
    )
    assert len(lookup) == len(df)
    assert lookup
    assert "train_samples" in metrics or metrics.get("ic") is not None or metrics == {}
