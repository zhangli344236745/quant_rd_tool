"""Optuna hyperparameter tuning for A-share VectorBT strategies."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from typing import Any

import optuna

from quant_rd_tool.stock_vbt_lab import VBT_LAB_DIR, evaluate_backtest_on_df, load_ohlcv
from quant_rd_tool.stock_vbt_strategies import get_strategy, validate_params

OPTUNA_DIR = VBT_LAB_DIR / "optuna"


def _iso_now(now: datetime | None = None) -> str:
    dt = now or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def suggest_strategy_params(trial: optuna.Trial, strategy_id: str) -> dict[str, Any]:
    spec = get_strategy(strategy_id)
    raw: dict[str, Any] = {}
    for p in spec["param_schema"]:
        name = p["name"]
        if p["type"] == "int":
            raw[name] = trial.suggest_int(name, int(p["min"]), int(p["max"]))
        else:
            raw[name] = trial.suggest_float(name, float(p["min"]), float(p["max"]))
    return validate_params(strategy_id, raw)


def _metric_sharpe(metrics: dict[str, Any]) -> float:
    sharpe = metrics.get("sharpe")
    if sharpe is None:
        return -999.0
    try:
        val = float(sharpe)
    except (TypeError, ValueError):
        return -999.0
    if math.isnan(val) or math.isinf(val):
        return -999.0
    return val


def run_optuna_tune(
    *,
    symbol: str,
    start: str,
    end: str,
    strategy_id: str,
    n_trials: int = 30,
    train_ratio: float = 0.7,
    capital_base: float = 100_000.0,
    data_dir: str = "data/stocks",
    refresh_data: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 0.5 <= train_ratio <= 0.9:
        raise ValueError("train_ratio must be between 0.5 and 0.9")
    if n_trials < 5:
        raise ValueError("n_trials must be >= 5")

    spec = get_strategy(strategy_id)
    min_bars = int(spec["min_bars"])
    df = load_ohlcv(symbol, start, end, data_dir=data_dir, refresh=refresh_data)
    split_idx = int(len(df) * train_ratio)
    if split_idx < min_bars + 10:
        raise ValueError("train split too short for strategy warmup")
    if len(df) - split_idx < min_bars:
        raise ValueError("test split too short for strategy warmup")

    train_df = df.iloc[:split_idx].reset_index(drop=True)
    test_df = df.iloc[split_idx:].reset_index(drop=True)

    def objective(trial: optuna.Trial) -> float:
        try:
            params = suggest_strategy_params(trial, strategy_id)
            result = evaluate_backtest_on_df(
                train_df,
                symbol=symbol,
                strategy_id=strategy_id,
                strategy_params=params,
                capital_base=capital_base,
            )
            return _metric_sharpe(result["metrics"])
        except ValueError:
            return -999.0

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = validate_params(strategy_id, study.best_params)
    train_result = evaluate_backtest_on_df(
        train_df,
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_params=best_params,
        capital_base=capital_base,
    )
    test_result = evaluate_backtest_on_df(
        test_df,
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_params=best_params,
        capital_base=capital_base,
    )

    run_id = str(uuid.uuid4())
    run_dir = OPTUNA_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    doc = {
        "run_id": run_id,
        "symbol": train_result["symbol"],
        "start": start,
        "end": end,
        "strategy_id": strategy_id,
        "n_trials": n_trials,
        "train_ratio": train_ratio,
        "best_params": best_params,
        "best_value": study.best_value,
        "train_metrics": {k: v for k, v in train_result["metrics"].items() if k != "engine"},
        "test_metrics": {k: v for k, v in test_result["metrics"].items() if k != "engine"},
        "created_at": _iso_now(now),
    }
    (run_dir / "best_params.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "run_id": run_id,
        "symbol": doc["symbol"],
        "strategy_id": strategy_id,
        "strategy_name": spec["name"],
        "best_params": best_params,
        "best_sharpe": study.best_value,
        "train_metrics": doc["train_metrics"],
        "test_metrics": doc["test_metrics"],
        "n_trials": n_trials,
        "train_ratio": train_ratio,
    }


def list_tune_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    if not OPTUNA_DIR.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    dirs = sorted(OPTUNA_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for run_dir in dirs:
        path = run_dir / "best_params.json"
        if not path.is_file():
            continue
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
        if len(rows) >= limit:
            break
    return rows
