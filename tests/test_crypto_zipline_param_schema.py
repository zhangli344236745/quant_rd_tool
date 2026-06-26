from __future__ import annotations

import pandas as pd
import pytest

from quant_rd_tool.crypto_zipline_param_schema import (
    TUNABLE_STRATEGY_IDS,
    get_param_schema,
    list_tunable_strategies,
    suggest_params,
    validate_params,
)


def test_list_tunable_strategies_has_param_schema():
    rows = list_tunable_strategies()
    assert len(rows) == len(TUNABLE_STRATEGY_IDS)
    for row in rows:
        assert row["param_schema"]
        assert row["id"] in TUNABLE_STRATEGY_IDS


def test_validate_ma_crossover_fast_lt_slow():
    with pytest.raises(ValueError, match="fast must be < slow"):
        validate_params("ma_crossover", {"fast": 30, "slow": 10})


def test_validate_ma_crossover_ok():
    params = validate_params("ma_crossover", {"fast": 8, "slow": 21})
    assert params["fast"] == 8
    assert params["slow"] == 21


def test_get_param_schema_unknown():
    with pytest.raises(ValueError, match="not tunable"):
        get_param_schema("xgb_alpha158")


def test_suggest_params_via_optuna_trial():
    import optuna

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial, "donchian_breakout")
        assert 5 <= params["channel"] <= 80
        return 1.0

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=3, show_progress_bar=False)


def test_compute_train_test_ranges():
    from quant_rd_tool.crypto_zipline_optuna import compute_train_test_ranges

    df = pd.DataFrame(
        {
            "date": [f"2026-01-{i:02d}" for i in range(1, 31)],
            "open": [1.0] * 30,
            "high": [1.0] * 30,
            "low": [1.0] * 30,
            "close": [1.0] * 30,
            "volume": [1.0] * 30,
        }
    )
    train_start, train_end, test_start, test_end = compute_train_test_ranges(
        df, train_ratio=0.7, min_bars=5
    )
    assert train_start == "2026-01-01"
    assert train_end == "2026-01-21"
    assert test_start == "2026-01-22"
    assert test_end == "2026-01-30"
