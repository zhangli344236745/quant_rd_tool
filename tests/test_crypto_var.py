import numpy as np
import pandas as pd
import pytest

from quant_rd_tool.crypto_var import (
    backtest_var,
    bars_per_day,
    build_portfolio_returns,
    build_portfolio_var_report,
    build_symbol_var_breach,
    build_symbol_var_report,
    compute_cvar,
    compute_historical_var,
    compute_monte_carlo_var,
    compute_parametric_var,
    confidence_key,
    correlation_matrix,
    parse_confidence_levels,
    resolve_horizon_days,
    returns_from_close,
    stress_scenarios,
)


def test_returns_from_close_simple():
    s = pd.Series([100.0, 110.0, 99.0])
    r = returns_from_close(s)
    assert len(r.dropna()) == 2
    assert r.iloc[-1] == pytest.approx(99.0 / 110.0 - 1)


def test_historical_var_known_series():
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0, 0.02, 200))
    var_pct = compute_historical_var(rets, confidence=0.95, horizon_days=1)
    assert var_pct > 0


def test_cvar_exceeds_var():
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.standard_t(5, size=500) * 0.02)
    var_pct = compute_historical_var(rets, confidence=0.95, horizon_days=1)
    cvar_pct = compute_cvar(rets, confidence=0.95, horizon_days=1)
    assert cvar_pct >= var_pct


def test_insufficient_data_raises():
    rets = pd.Series([0.01, -0.02])
    with pytest.raises(ValueError, match="insufficient"):
        compute_historical_var(rets, confidence=0.95, horizon_days=1)


def test_parse_confidence_levels():
    assert parse_confidence_levels("0.95,0.99") == [0.95, 0.99]
    assert parse_confidence_levels("") == [0.95, 0.99]


def test_confidence_key():
    assert confidence_key(0.95) == "0.95"
    assert confidence_key(0.99) == "0.99"


def test_monte_carlo_var_reproducible():
    rng = np.random.default_rng(99)
    rets = pd.Series(rng.normal(0, 0.02, 120))
    a = compute_monte_carlo_var(rets, confidence=0.95, n_sims=5000, seed=7)
    b = compute_monte_carlo_var(rets, confidence=0.95, n_sims=5000, seed=7)
    assert a["gbm"]["var_pct"] == b["gbm"]["var_pct"]
    assert a["student_t"]["var_pct"] == b["student_t"]["var_pct"]
    assert a["gbm"]["var_pct"] > 0
    assert a["student_t"]["df"] >= 3.5


def test_monte_carlo_t_fatter_tail_than_gbm():
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.standard_t(4, size=400) * 0.025)
    mc = compute_monte_carlo_var(rets, confidence=0.99, n_sims=8000, seed=1)
    assert mc["student_t"]["var_pct"] >= mc["gbm"]["var_pct"]


def test_parametric_var_positive():
    rng = np.random.default_rng(1)
    rets = pd.Series(rng.normal(0, 0.02, 100))
    pvar = compute_parametric_var(rets, confidence=0.95, horizon_days=1)
    hvar = compute_historical_var(rets, confidence=0.95, horizon_days=1)
    assert pvar > 0
    assert hvar > 0


def test_backtest_var_counts_violations():
    rets = pd.Series([-0.05, 0.01, -0.08, 0.02, -0.03] * 20)
    var_pct = 0.04
    bt = backtest_var(rets, var_pct, confidence=0.95)
    assert bt["violations"] >= 1
    assert bt["actual_violation_rate"] > 0


def test_stress_scenarios():
    rows = stress_scenarios(10_000)
    assert len(rows) == 4
    assert rows[0]["loss_usdt"] == 300.0


def test_correlation_matrix():
    idx = pd.date_range("2024-01-01", periods=50, freq="D")
    rets_map = {
        "BTC": pd.Series(np.random.default_rng(0).normal(0, 0.01, 50), index=idx),
        "ETH": pd.Series(np.random.default_rng(1).normal(0, 0.012, 50), index=idx),
    }
    corr = correlation_matrix(rets_map)
    assert len(corr["symbols"]) == 2
    assert len(corr["matrix"]) == 2


def test_build_symbol_var_report(monkeypatch):
    from quant_rd_tool import crypto_var as cv

    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    close = pd.Series(
        100 * (1 + np.random.default_rng(1).normal(0, 0.01, 100)).cumprod(),
        index=dates,
    )
    df = pd.DataFrame({"date": dates, "close": close, "symbol": "BTC"})

    monkeypatch.setattr(cv, "fetch_ohlcv_df", lambda **kw: df)

    report = cv.build_symbol_var_report(
        symbol="BTC",
        notional_usdt=10_000,
        lookback_bars=90,
        confidence_levels=[0.95, 0.99],
        horizon_days=1,
        timeframe="1d",
    )
    assert report["symbol"] == "BTC"
    assert "0.95" in report["metrics"]
    assert report["metrics"]["0.95"]["var_usdt"] > 0
    assert report["metrics"]["0.95"]["parametric_var_pct"] is not None
    mc = report["metrics"]["0.95"].get("monte_carlo")
    assert mc and mc["gbm"]["var_pct"] > 0 and mc["student_t"]["var_pct"] > 0
    assert report.get("return_stats")
    assert report.get("narrative", {}).get("headline")
    assert len(report.get("stress_scenarios", [])) >= 1


def test_build_symbol_var_report_default_notional(monkeypatch):
    from quant_rd_tool import crypto_var as cv

    dates = pd.date_range("2024-01-01", periods=80, freq="D")
    close = pd.Series(np.linspace(100, 120, 80), index=dates)
    df = pd.DataFrame({"date": dates, "close": close})

    monkeypatch.setattr(cv, "fetch_ohlcv_df", lambda **kw: df)

    report = cv.build_symbol_var_report(
        symbol="ETH",
        notional_usdt=0,
        lookback_bars=60,
        confidence_levels=[0.95],
    )
    assert report["notional_usdt"] == pytest.approx(120.0)


def test_portfolio_returns_long_short():
    weights = {"BTC": 0.6, "ETH": -0.4}
    rets_map = {
        "BTC": pd.Series([0.01, -0.02, 0.03]),
        "ETH": pd.Series([0.02, -0.01, 0.01]),
    }
    port = build_portfolio_returns(weights, rets_map)
    assert len(port) == 3
    assert port.iloc[0] == pytest.approx(0.6 * 0.01 + (-0.4) * 0.02)


def test_build_portfolio_var_report_empty_positions(monkeypatch):
    from quant_rd_tool import crypto_var as cv

    monkeypatch.setattr(cv.settings, "binance_api_key", "k")
    monkeypatch.setattr(cv.settings, "binance_api_secret", "s")
    monkeypatch.setattr(cv, "fetch_all_open_positions", lambda **kw: [])

    report = build_portfolio_var_report(
        testnet=False,
        timeframe="1d",
        lookback_bars=60,
        horizon_days=1,
        confidence_levels=[0.95],
    )
    assert report["positions"] == []
    assert report.get("metrics") is None
    assert report.get("message") == "no open positions"


def test_build_portfolio_var_report_missing_api_keys(monkeypatch):
    from quant_rd_tool import crypto_var as cv

    monkeypatch.setattr(cv.settings, "binance_api_key", None)
    monkeypatch.setattr(cv.settings, "binance_api_secret", None)

    report = build_portfolio_var_report(testnet=False, confidence_levels=[0.95])
    assert report["enabled"] is False
    assert "missing api key" in report.get("error", "")


def test_build_portfolio_var_report_with_positions(monkeypatch):
    from quant_rd_tool import crypto_var as cv

    monkeypatch.setattr(cv.settings, "binance_api_key", "k")
    monkeypatch.setattr(cv.settings, "binance_api_secret", "s")
    monkeypatch.setattr(
        cv,
        "fetch_all_open_positions",
        lambda **kw: [
            {"base": "BTC", "side": "long", "symbol": "BTC/USDT:USDT", "signed_notional_usdt": 6000.0},
            {"base": "ETH", "side": "short", "symbol": "ETH/USDT:USDT", "signed_notional_usdt": -4000.0},
        ],
    )

    def fake_rets_map(bases, **kw):
        n = 80
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        rng = np.random.default_rng(7)
        return {
            "BTC": pd.Series(rng.normal(0, 0.01, n), index=idx),
            "ETH": pd.Series(rng.normal(0, 0.012, n), index=idx),
        }

    monkeypatch.setattr(cv, "_returns_map_for_bases", fake_rets_map)
    monkeypatch.setattr(cv, "_account_equity_usdt", lambda **kw: 50_000.0)

    report = build_portfolio_var_report(
        testnet=False,
        lookback_bars=60,
        confidence_levels=[0.95, 0.99],
    )
    assert report["enabled"] is True
    assert len(report["positions"]) == 2
    assert "0.99" in report["metrics"]
    assert report["gross_exposure_usdt"] == pytest.approx(10_000.0)
    assert report["diversification_ratio"] is not None
    assert report.get("correlation", {}).get("matrix")
    assert report["positions"][0].get("var_contribution_usdt") is not None
    assert report.get("narrative", {}).get("headline")


def test_build_symbol_var_history(monkeypatch):
    from quant_rd_tool import crypto_var as cv

    n = 120
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(100 * (1 + np.random.default_rng(3).normal(0, 0.008, n)).cumprod(), index=dates)
    df = pd.DataFrame({"date": dates, "close": close})
    monkeypatch.setattr(cv, "fetch_ohlcv_df", lambda **kw: df)

    out = cv.build_symbol_var_history(
        "BTC",
        window=10,
        confidence=0.99,
        lookback_bars=40,
        notional_usdt=5000,
    )
    assert out["symbol"] == "BTC"
    assert len(out["series"]) > 0
    assert "var_pct" in out["series"][0]
    assert out["series"][0]["var_usdt"] > 0


def test_resolve_horizon_days_intraday():
    assert resolve_horizon_days(horizon_bars=6, timeframe="4h") == pytest.approx(1.0)
    assert resolve_horizon_days(horizon_bars=24, timeframe="1h") == pytest.approx(1.0)
    assert resolve_horizon_days(horizon_days=3, timeframe="1d") == 3.0
    assert bars_per_day("4h") == 6.0


def test_horizon_bars_scales_var():
    rng = np.random.default_rng(11)
    rets = pd.Series(rng.normal(0, 0.02, 200))
    v1 = compute_historical_var(rets, confidence=0.95, horizon_days=1.0)
    v4h = compute_historical_var(rets, confidence=0.95, horizon_days=4 / 24)
    v4d = compute_historical_var(rets, confidence=0.95, horizon_days=4.0)
    assert v4h <= v1
    assert v4d >= v1


def test_build_symbol_var_breach_detects_tail(monkeypatch):
    from quant_rd_tool import crypto_var as cv

    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="4h")
    rng = np.random.default_rng(5)
    rets_raw = rng.normal(0, 0.005, n)
    rets_raw[-1] = -0.12
    close = pd.Series(100 * (1 + rets_raw).cumprod(), index=dates)
    df = pd.DataFrame({"date": dates, "close": close})
    monkeypatch.setattr(cv, "fetch_ohlcv_df", lambda **kw: df)

    out = cv.build_symbol_var_breach(
        "BTC",
        confidence=0.95,
        lookback_bars=60,
        horizon_bars=1,
        timeframe="4h",
        notional_usdt=10_000,
    )
    assert out["breached"] is True
    assert out["actual_return"] < 0
    assert out["var_usdt"] > 0


def test_build_symbol_var_breach_no_breach(monkeypatch):
    from quant_rd_tool import crypto_var as cv

    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = pd.Series(100 * (1 + np.random.default_rng(2).normal(0, 0.002, n)).cumprod(), index=dates)
    df = pd.DataFrame({"date": dates, "close": close})
    monkeypatch.setattr(cv, "fetch_ohlcv_df", lambda **kw: df)

    out = cv.build_symbol_var_breach(
        "ETH",
        confidence=0.99,
        lookback_bars=60,
        horizon_bars=1,
        timeframe="1h",
        notional_usdt=5000,
    )
    assert out["breached"] is False
    assert out["severity"] == "none"
