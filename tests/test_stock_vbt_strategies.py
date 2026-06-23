from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quant_rd_tool.stock_vbt_strategies import build_target_series, get_strategy, list_strategies


def _fixture_df() -> pd.DataFrame:
    path = Path(__file__).parent / "fixtures" / "ashare_vbt_daily.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    return df


def test_list_strategies_has_four():
    ids = {s["id"] for s in list_strategies()}
    assert ids == {"sma_cross", "rsi_revert", "macd_cross", "bb_breakout"}


@pytest.mark.parametrize("sid", ["sma_cross", "rsi_revert", "macd_cross", "bb_breakout"])
def test_build_target_binary(sid):
    df = _fixture_df()
    spec = get_strategy(sid)
    out = build_target_series(df, sid, spec["default_params"])
    assert "target" in out.columns
    assert set(out["target"].dropna().unique()).issubset({0.0, 1.0})


def test_sma_fast_must_be_less_than_slow():
    df = _fixture_df()
    with pytest.raises(ValueError, match="fast must be < slow"):
        build_target_series(df, "sma_cross", {"fast": 30, "slow": 10})
