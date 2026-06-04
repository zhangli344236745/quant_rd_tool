from __future__ import annotations

import pandas as pd

from quant_rd_tool.crypto_zipline_combo import (
    combine_targets,
    normalize_combo_spec,
    run_combo_pandas,
)
from quant_rd_tool.crypto_zipline_timeframes import normalize_timeframe


def _sample_df(n: int = 80) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        price += (1 if i % 7 < 4 else -1) * 0.5
        rows.append(
            {
                "date": f"2026-01-{(i % 28) + 1:02d} 12:00:00",
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 1000 + i,
            }
        )
    return pd.DataFrame(rows)


def test_normalize_combo_spec():
    spec = normalize_combo_spec(
        legs=[{"strategy": "ma_crossover"}, {"strategy": "momentum_rsi", "weight": 2}],
        mode="vote",
    )
    assert spec["mode"] == "vote"
    assert len(spec["legs"]) == 2
    assert spec["legs"][1]["weight"] == 2.0


def test_combine_targets_modes():
    assert combine_targets([1.0, 1.0], [1, 1], "and") == 1.0
    assert combine_targets([0.0, 1.0], [1, 1], "or") == 1.0
    assert combine_targets([1.0, 1.0, 0.0], [1, 1, 1], "vote") == 1.0
    assert combine_targets([1.0, 0.0], [2, 1], "weighted") == 1.0


def test_run_combo_pandas():
    df = _sample_df(100)
    spec = normalize_combo_spec(
        legs=[{"strategy": "ma_crossover", "params": {"fast": 5, "slow": 15}}],
        mode="vote",
    )
    out = run_combo_pandas(df, spec, 10_000)
    assert "metrics" in out
    assert out["combo_legs"] == ["ma_crossover"]


def test_timeframe_normalize():
    assert normalize_timeframe("1H") == "1h"
    assert normalize_timeframe("15m") == "15m"
