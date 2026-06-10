"""Tests for walk-forward XGB ML layer."""

import numpy as np
import pandas as pd

from quant_rd_tool.crypto_zipline_ml import compute_walk_forward_targets
from quant_rd_tool.crypto_zipline_ml_features import build_ml_feature_frame, forward_return_labels


def _synthetic_df(n: int = 800) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": rng.uniform(100, 1000, n),
        }
    )


def test_forward_labels_no_future_in_features():
    df = _synthetic_df(200)
    feats = build_ml_feature_frame(df.iloc[:100], include_tv=False)
    feats_full = build_ml_feature_frame(df, include_tv=False)
    pd.testing.assert_frame_equal(feats, feats_full.iloc[:100])


def test_walk_forward_produces_targets():
    df = _synthetic_df(1200)
    params = {"train_bars": 400, "retrain_every": 200, "min_train_samples": 100}
    targets, metrics = compute_walk_forward_targets(df, params, timeframe="15m", include_tv=False)
    assert len(targets) == len(df)
    assert targets.iloc[500:].sum() >= 0
    assert "train_samples" in metrics or targets.iloc[450:].notna().any()


def test_walk_forward_no_peek_at_early_targets():
    df = _synthetic_df(1000)
    params = {"train_bars": 300, "retrain_every": 150, "min_train_samples": 80}
    t1, _ = compute_walk_forward_targets(df, params, timeframe="15m", include_tv=False)
    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc("close")] = df2["close"].iloc[-1] * 1.5
    t2, _ = compute_walk_forward_targets(df2, params, timeframe="15m", include_tv=False)
    # early targets should be identical (last bar change must not affect t < n-2)
    compare_end = len(df) - 3
    if compare_end > 400:
        pd.testing.assert_series_equal(t1.iloc[400:compare_end], t2.iloc[400:compare_end])
