from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quant_rd_tool.stock_vbt_ml import build_feature_matrix, screen_universe
from quant_rd_tool.stock_vbt_optuna import suggest_strategy_params
from quant_rd_tool.stock_vbt_portfolio import backtest_portfolio, optimize_portfolio


def test_build_feature_matrix():
    idx = pd.date_range("2020-01-01", periods=100, freq="B")
    close = pd.Series(range(100, 200), index=idx, dtype=float)
    df = pd.DataFrame({"close": close})
    feats = build_feature_matrix(df)
    assert len(feats) > 30
    assert "label" in feats.columns


def test_suggest_strategy_params():
    import optuna

    study = optuna.create_study()
    trial = study.ask()
    params = suggest_strategy_params(trial, "sma_cross")
    assert params["fast"] < params["slow"]


def test_optimize_portfolio_on_fixture(monkeypatch, tmp_path):
    from quant_rd_tool import stock_vbt_portfolio as port

    fixture = Path(__file__).parent / "fixtures" / "ashare_vbt_daily.csv"
    df = pd.read_csv(fixture, parse_dates=["date"])

    def _fake_load(sym, start, end, **kw):
        out = df.copy()
        out["symbol"] = sym
        return out

    monkeypatch.setattr(port, "load_ohlcv", _fake_load)
    result = optimize_portfolio(
        symbols=["600519", "600519"],
        start="2023-01-02",
        end="2023-04-24",
        lookback_days=60,
    )
    assert result["weights"]
    assert "sharpe_ratio" in result


def test_backtest_portfolio_weights(monkeypatch):
    from quant_rd_tool import stock_vbt_portfolio as port

    fixture = Path(__file__).parent / "fixtures" / "ashare_vbt_daily.csv"
    df = pd.read_csv(fixture, parse_dates=["date"])

    def _fake_load(sym, start, end, **kw):
        return df.copy()

    monkeypatch.setattr(port, "load_ohlcv", _fake_load)
    bt = backtest_portfolio(
        weights={"SH600519": 1.0},
        start="2023-01-02",
        end="2023-04-24",
    )
    assert bt["equity_curve"]
    assert "total_return" in bt


def test_screen_universe_mock(monkeypatch, tmp_path):
    from quant_rd_tool import stock_vbt_ml as ml

    monkeypatch.setattr(ml, "ML_DIR", tmp_path)
    monkeypatch.setattr(
        ml,
        "score_symbol",
        lambda sym, start, end, **kw: {
            "symbol": f"SH{sym}",
            "score": float(sym) if sym.isdigit() else 0.5,
            "expected_fwd_return_5d": 0.01,
            "algorithm": "lgb",
            "train_samples": 100,
            "feature_importance": {},
        },
    )
    out = screen_universe(symbols=["600519", "000001"], start="2023-01-01", end="2023-06-01", top_k=2)
    assert len(out["items"]) == 2
    assert (tmp_path / out["run_id"] / "scores.json").is_file()
