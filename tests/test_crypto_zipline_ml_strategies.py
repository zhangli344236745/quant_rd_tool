"""End-to-end ML strategy backtest smoke tests."""

import numpy as np
import pandas as pd

from quant_rd_tool.crypto_zipline_ml import run_ml_strategy


def _synthetic_df(n: int = 1500) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": rng.uniform(500, 2000, n),
        }
    )


def test_xgb_alpha158_smoke():
    df = _synthetic_df()
    out = run_ml_strategy(
        df,
        strategy_id="xgb_alpha158",
        params={"train_bars": 400, "retrain_every": 200, "min_train_samples": 80},
        capital_base=100_000,
        timeframe="15m",
    )
    assert "metrics" in out
    assert out["metrics"]["trade_count"] >= 0
    assert "ml_metrics" in out


def test_xgb_tv_filter_smoke():
    df = _synthetic_df()
    out = run_ml_strategy(
        df,
        strategy_id="xgb_tv_filter",
        params={
            "base_strategy": "supertrend",
            "train_bars": 400,
            "retrain_every": 200,
            "min_train_samples": 80,
        },
        capital_base=100_000,
        timeframe="15m",
    )
    assert out.get("ml_metrics", {}).get("base_strategy") == "supertrend"
