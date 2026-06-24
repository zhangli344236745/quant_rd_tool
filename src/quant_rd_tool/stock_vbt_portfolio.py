"""Portfolio optimization for A-share VectorBT lab."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pypfopt import EfficientFrontier, expected_returns, risk_models

from quant_rd_tool.stock_codes import to_qlib_code
from quant_rd_tool.stock_vbt_lab import VBT_LAB_DIR, load_ohlcv

PortfolioMethod = Literal["max_sharpe", "min_volatility"]
PORTFOLIO_DIR = VBT_LAB_DIR / "portfolio"


from quant_rd_tool.time_util import to_beijing_iso


def _iso_now(now: datetime | None = None) -> str:
    return to_beijing_iso(now)


def _load_price_panel(
    symbols: list[str],
    start: str,
    end: str,
    *,
    data_dir: str,
    refresh_data: bool,
    lookback_days: int | None,
) -> pd.DataFrame:
    if not symbols:
        raise ValueError("symbols required")
    series_map: dict[str, pd.Series] = {}
    for sym in symbols:
        df = load_ohlcv(sym, start, end, data_dir=data_dir, refresh=refresh_data)
        code = to_qlib_code(sym)
        s = df.set_index(pd.to_datetime(df["date"]))["close"].astype(float).rename(code)
        series_map[code] = s
    prices = pd.DataFrame(series_map).sort_index().dropna(how="any")
    if lookback_days and len(prices) > lookback_days:
        prices = prices.iloc[-lookback_days:]
    if len(prices) < 30:
        raise ValueError("need at least 30 aligned trading days")
    return prices


def optimize_portfolio(
    *,
    symbols: list[str],
    start: str,
    end: str,
    method: PortfolioMethod = "max_sharpe",
    lookback_days: int | None = 252,
    data_dir: str = "data/stocks",
    refresh_data: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    prices = _load_price_panel(
        symbols,
        start,
        end,
        data_dir=data_dir,
        refresh_data=refresh_data,
        lookback_days=lookback_days,
    )
    mu = expected_returns.mean_historical_return(prices)
    cov = risk_models.sample_cov(prices)
    ef = EfficientFrontier(mu, cov)
    if method == "min_volatility":
        ef.min_volatility()
    else:
        ef.max_sharpe()
    cleaned = ef.clean_weights()
    perf = ef.portfolio_performance()

    run_id = str(uuid.uuid4())
    run_dir = PORTFOLIO_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "run_id": run_id,
        "symbols": list(cleaned.keys()),
        "method": method,
        "start": start,
        "end": end,
        "lookback_days": lookback_days,
        "weights": cleaned,
        "expected_annual_return": perf[0],
        "annual_volatility": perf[1],
        "sharpe_ratio": perf[2],
        "created_at": _iso_now(now),
    }
    (run_dir / "weights.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "run_id": run_id,
        "weights": cleaned,
        "method": method,
        "expected_annual_return": perf[0],
        "annual_volatility": perf[1],
        "sharpe_ratio": perf[2],
        "symbols": list(cleaned.keys()),
    }


def backtest_portfolio(
    *,
    weights: dict[str, float],
    start: str,
    end: str,
    capital_base: float = 100_000.0,
    data_dir: str = "data/stocks",
    refresh_data: bool = False,
) -> dict[str, Any]:
    if not weights:
        raise ValueError("weights required")
    symbols = list(weights.keys())
    prices = _load_price_panel(
        symbols,
        start,
        end,
        data_dir=data_dir,
        refresh_data=refresh_data,
        lookback_days=None,
    )
    rets = prices.pct_change().dropna()
    w = pd.Series({k: float(v) for k, v in weights.items()})
    w = w / w.sum()
    port_ret = (rets * w).sum(axis=1)
    equity = (1 + port_ret).cumprod() * capital_base
    total_return = float(equity.iloc[-1] / capital_base - 1)
    vol = float(port_ret.std() * (252**0.5))
    sharpe = float(port_ret.mean() / port_ret.std() * (252**0.5)) if port_ret.std() > 0 else 0.0
    peak = equity.cummax()
    max_dd = float(((equity / peak) - 1).min())

    curve = [
        {"time": idx.strftime("%Y-%m-%d"), "value": float(val)}
        for idx, val in equity.items()
    ]
    return {
        "capital_base": capital_base,
        "total_return": total_return,
        "sharpe": sharpe,
        "volatility": vol,
        "max_drawdown": max_dd,
        "equity_curve": curve,
    }
