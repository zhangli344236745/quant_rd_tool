"""API routes for A-share VectorBT lab."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()

_RUN_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


class VbtBacktestRequest(BaseModel):
    symbol: str
    start: str
    end: str
    strategy_id: str
    strategy_params: dict[str, Any] | None = None
    capital_base: float = Field(default=100_000.0, gt=0)
    refresh_data: bool = False
    data_dir: str = "data/stocks"


def _validate_run_id(run_id: str) -> str:
    rid = run_id.strip()
    if not _RUN_ID_RE.match(rid):
        raise HTTPException(status_code=400, detail="invalid run_id")
    return rid


@router.get("/strategies")
def vbt_strategies() -> list[dict[str, Any]]:
    from quant_rd_tool.stock_vbt_strategies import list_strategies

    return list_strategies()


@router.post("/backtest")
def vbt_backtest(body: VbtBacktestRequest) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_lab import run_backtest

    try:
        result = run_backtest(
            symbol=body.symbol,
            start=body.start,
            end=body.end,
            strategy_id=body.strategy_id,
            strategy_params=body.strategy_params,
            capital_base=body.capital_base,
            data_dir=body.data_dir,
            refresh_data=body.refresh_data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {
        "run_id": result["run_id"],
        "symbol": result["symbol"],
        "strategy_id": result["strategy_id"],
        "strategy_name": result["strategy_name"],
        "metrics": result["metrics"],
        "execution_stats": result["execution_stats"],
        "trades_count": result["trades_count"],
        "equity_curve": result["equity_curve"],
        "trades": result["trades"],
    }


@router.get("/runs")
def vbt_runs(
    limit: int = Query(default=20, ge=1, le=100),
    symbol: str | None = None,
) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_lab import list_runs

    return {"items": list_runs(limit=limit, symbol=symbol)}


@router.get("/runs/{run_id}")
def vbt_run_detail(run_id: str) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_lab import get_run

    rid = _validate_run_id(run_id)
    try:
        return get_run(rid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/runs/{run_id}/equity")
def vbt_run_equity(run_id: str) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_lab import get_run

    rid = _validate_run_id(run_id)
    try:
        run = get_run(rid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"run_id": rid, "equity_curve": run.get("equity_curve", [])}


@router.get("/runs/{run_id}/trades")
def vbt_run_trades(run_id: str) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_lab import get_run

    rid = _validate_run_id(run_id)
    try:
        run = get_run(rid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"run_id": rid, "trades": run.get("trades", [])}


class VbtTuneRequest(BaseModel):
    symbol: str
    start: str
    end: str
    strategy_id: str
    n_trials: int = Field(default=30, ge=5, le=200)
    train_ratio: float = Field(default=0.7, ge=0.5, le=0.9)
    capital_base: float = Field(default=100_000.0, gt=0)
    refresh_data: bool = False
    data_dir: str = "data/stocks"


@router.post("/tune")
def vbt_tune(body: VbtTuneRequest) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_optuna import run_optuna_tune

    try:
        return run_optuna_tune(
            symbol=body.symbol,
            start=body.start,
            end=body.end,
            strategy_id=body.strategy_id,
            n_trials=body.n_trials,
            train_ratio=body.train_ratio,
            capital_base=body.capital_base,
            data_dir=body.data_dir,
            refresh_data=body.refresh_data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/tune/runs")
def vbt_tune_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_optuna import list_tune_runs

    return {"items": list_tune_runs(limit=limit)}


class VbtMlScoreRequest(BaseModel):
    symbols: list[str] | None = None
    start: str
    end: str
    top_k: int = Field(default=10, ge=1, le=50)
    algorithm: str = "lgb"
    use_watchlist: bool = False
    refresh_data: bool = False
    data_dir: str = "data/stocks"


@router.post("/ml/score")
def vbt_ml_score(body: VbtMlScoreRequest) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_ml import screen_universe

    algo = body.algorithm.strip().lower()
    if algo not in ("lgb", "xgb"):
        raise HTTPException(status_code=400, detail="algorithm must be lgb or xgb")
    try:
        return screen_universe(
            symbols=body.symbols,
            start=body.start,
            end=body.end,
            top_k=body.top_k,
            algorithm=algo,  # type: ignore[arg-type]
            use_watchlist=body.use_watchlist,
            data_dir=body.data_dir,
            refresh_data=body.refresh_data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


class VbtPortfolioRequest(BaseModel):
    symbols: list[str]
    start: str
    end: str
    method: str = "max_sharpe"
    lookback_days: int | None = Field(default=252, ge=30, le=1000)
    refresh_data: bool = False
    data_dir: str = "data/stocks"
    with_backtest: bool = False
    capital_base: float = Field(default=100_000.0, gt=0)


@router.post("/portfolio/optimize")
def vbt_portfolio_optimize(body: VbtPortfolioRequest) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_portfolio import backtest_portfolio, optimize_portfolio

    method = body.method.strip().lower()
    if method not in ("max_sharpe", "min_volatility"):
        raise HTTPException(status_code=400, detail="method must be max_sharpe or min_volatility")
    try:
        result = optimize_portfolio(
            symbols=body.symbols,
            start=body.start,
            end=body.end,
            method=method,  # type: ignore[arg-type]
            lookback_days=body.lookback_days,
            data_dir=body.data_dir,
            refresh_data=body.refresh_data,
        )
        if body.with_backtest:
            bt = backtest_portfolio(
                weights=result["weights"],
                start=body.start,
                end=body.end,
                capital_base=body.capital_base,
                data_dir=body.data_dir,
                refresh_data=body.refresh_data,
            )
            result["backtest"] = bt
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


class VbtSchedulerConfigRequest(BaseModel):
    enabled: bool | None = None
    cron_hour: int | None = Field(default=None, ge=0, le=23)
    cron_minute: int | None = Field(default=None, ge=0, le=59)
    symbols: list[str] | None = None
    use_watchlist: bool | None = None
    strategy_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    ml_algorithm: str | None = None
    portfolio_method: str | None = None
    lookback_days: int | None = Field(default=None, ge=30, le=1000)
    start: str | None = None
    end: str | None = None
    data_dir: str | None = None
    refresh_data: bool | None = None
    optuna_trials: int | None = Field(default=None, ge=0, le=100)


@router.get("/scheduler/status")
def vbt_scheduler_status() -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_scheduler import get_vbt_scheduler

    return get_vbt_scheduler().status()


@router.post("/scheduler/config")
def vbt_scheduler_config(body: VbtSchedulerConfigRequest) -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_scheduler import get_vbt_scheduler

    updates = body.model_dump(exclude_none=True)
    cfg = get_vbt_scheduler().update_config(updates)
    return {"config": cfg}


@router.post("/scheduler/start")
def vbt_scheduler_start() -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_scheduler import get_vbt_scheduler

    return get_vbt_scheduler().start()


@router.post("/scheduler/stop")
def vbt_scheduler_stop() -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_scheduler import get_vbt_scheduler

    return get_vbt_scheduler().stop()


@router.post("/scheduler/trigger")
def vbt_scheduler_trigger() -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_scheduler import get_vbt_scheduler

    try:
        result = get_vbt_scheduler().trigger()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"ok": True, "result": result}


@router.get("/signals/latest")
def vbt_signals_latest() -> dict[str, Any]:
    from quant_rd_tool.stock_vbt_scheduler import get_latest_signals

    sig = get_latest_signals()
    if sig is None:
        return {"available": False}
    return {"available": True, "signals": sig}
