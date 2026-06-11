from __future__ import annotations

from quant_rd_tool.stock_zipline_strategies import is_stock_strategy, list_stock_strategies
from quant_rd_tool.stock_zipline_timeframes import effective_ml_train_bars, ml_window_scale


def test_list_stock_strategies_excludes_options():
    ids = {s["id"] for s in list_stock_strategies()}
    assert "ma_crossover" in ids
    assert "xgb_alpha158" in ids
    assert "opt_call_overlay" not in ids
    assert "opt_auto_pack" not in ids
    for sid in ids:
        assert not sid.startswith("opt_")


def test_is_stock_strategy_rejects_options():
    assert is_stock_strategy("ma_crossover")
    assert is_stock_strategy("xgb_tv_filter")
    assert not is_stock_strategy("opt_call_overlay")
    assert not is_stock_strategy("opt_put_hedge")


def test_stock_ml_window_scale_daily():
    assert ml_window_scale("1d") == 0.05
    assert effective_ml_train_bars("1d", 2000) == 100


def test_run_backtest_rejects_options_strategy():
    import pytest

    from quant_rd_tool.stock_zipline_runner import run_backtest

    with pytest.raises(ValueError, match="not available"):
        run_backtest(
            symbol="600519",
            data_dir="data/stocks",
            strategy_id="opt_call_overlay",
            start="2024-01-01",
            end="2025-06-01",
            engine="pandas",
        )
