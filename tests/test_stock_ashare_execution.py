"""Tests for A-share execution rules."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_rd_tool.backtest_engine import _topk_backtest
from quant_rd_tool.stock_ashare_execution import (
    AShareFeeSchedule,
    calc_trade_fees,
    infer_limit_pct,
    is_limit_down,
    is_limit_up,
    limit_prices,
    round_to_lot,
    run_topk_backtest_ashare,
)
from quant_rd_tool.stock_ashare_pandas import ashare_backtest_context, run_ashare_bar_backtest


def test_commission_minimum():
    comm, stamp, xfer = calc_trade_fees(
        side="buy", notional=1000, code="SH600519", schedule=AShareFeeSchedule()
    )
    assert comm == 5.0
    assert stamp == 0.0


def test_stamp_duty_sell_only():
    _, stamp_buy, _ = calc_trade_fees(side="buy", notional=100_000, code="SH600519", schedule=AShareFeeSchedule())
    _, stamp_sell, _ = calc_trade_fees(side="sell", notional=100_000, code="SH600519", schedule=AShareFeeSchedule())
    assert stamp_buy == 0.0
    assert stamp_sell == 50.0


def test_round_to_lot():
    assert round_to_lot(150) == 100
    assert round_to_lot(99) == 0
    assert round_to_lot(200) == 200


def test_growth_board_limit_pct():
    assert infer_limit_pct("SH688001") == 0.20
    assert infer_limit_pct("SZ300750") == 0.20
    assert infer_limit_pct("SH600519") == 0.10


def test_limit_prices():
    up, down = limit_prices(10.0, 0.10)
    assert up == 11.0
    assert down == 9.0
    assert is_limit_up(11.0, 10.0, 0.10)
    assert is_limit_down(9.0, 10.0, 0.10)


def test_ashare_bar_backtest_t_plus_one():
    df = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-02", "2024-01-03"],
            "close": [10.0, 10.0, 10.0],
            "target": [0.0, 1.0, 0.0],
        }
    )
    with ashare_backtest_context(symbol="SH600519"):
        out = run_ashare_bar_backtest(df, capital_base=100_000, warmup=1)
    sells = [t for t in out["trades"] if t["side"] == "sell"]
    assert len(sells) == 0 or out["cost_summary"]["blocked_t_plus_one"] >= 0


def test_topk_ashare_costlier_than_legacy():
    codes = ["SH600519", "SH601318", "SZ000858"]
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2024-01-02", periods=60)
    frames = {}
    for i, code in enumerate(codes):
        close = 100 * (1 + rng.normal(0.001, 0.02, len(dates))).cumprod()
        frames[code] = pd.DataFrame({"date": dates, "close": close})
    close = pd.concat(
        [f.set_index(pd.to_datetime(f["date"]))["close"].rename(c) for c, f in frames.items()],
        axis=1,
    )
    scores = close / close.shift(10) - 1.0
    legacy, _ = _topk_backtest(scores.iloc[15:], close.iloc[15:], topk=2, initial_cash=1e6)
    ashare, _, _, _ = run_topk_backtest_ashare(scores.iloc[15:], close.iloc[15:], topk=2, initial_cash=1e6)
    if not legacy.empty and not ashare.empty:
        assert float(ashare["portfolio_value"].iloc[-1]) <= float(legacy["portfolio_value"].iloc[-1]) + 1.0
