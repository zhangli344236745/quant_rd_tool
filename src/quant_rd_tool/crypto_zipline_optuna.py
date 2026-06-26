"""Optuna hyperparameter tuning for crypto zipline strategies (subprocess engine)."""

from __future__ import annotations

import json
import math
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import optuna
import pandas as pd

from quant_rd_tool.crypto_zipline_bundle import load_ohlcv_window
from quant_rd_tool.crypto_zipline_param_schema import (
    TUNABLE_STRATEGY_IDS,
    suggest_params,
    validate_params,
)
from quant_rd_tool.crypto_zipline_runner import run_zipline_backtest
from quant_rd_tool.crypto_zipline_strategies import get_strategy
from quant_rd_tool.crypto_zipline_timeframes import DEFAULT_TIMEFRAME, normalize_timeframe
from quant_rd_tool.time_util import to_beijing_iso

OPTUNA_DIR = Path("data/crypto/zipline/optuna")


def _iso_now(now: datetime | None = None) -> str:
    return to_beijing_iso(now)


def _row_date_str(row: pd.Series) -> str:
    if "date" in row.index and pd.notna(row["date"]):
        s = str(row["date"])
        return s[:10] if len(s) >= 10 else s
    ts = pd.to_datetime(row["timestamp"], unit="ms", utc=True)
    return ts.strftime("%Y-%m-%d")


def _metric_value(metrics: dict[str, Any], objective: str) -> float:
    if objective == "total_return":
        key = "total_return"
    elif objective == "calmar":
        tr = metrics.get("total_return")
        mdd = metrics.get("max_drawdown")
        if tr is None or mdd is None:
            return -999.0
        try:
            tr_f = float(tr)
            mdd_f = abs(float(mdd))
        except (TypeError, ValueError):
            return -999.0
        if mdd_f < 1e-9:
            return -999.0
        val = tr_f / mdd_f
        if math.isnan(val) or math.isinf(val):
            return -999.0
        return val
    else:
        key = "sharpe"

    val_raw = metrics.get(key)
    if val_raw is None:
        return -999.0
    try:
        val = float(val_raw)
    except (TypeError, ValueError):
        return -999.0
    if math.isnan(val) or math.isinf(val):
        return -999.0
    return val


def compute_train_test_ranges(
    df: pd.DataFrame,
    *,
    train_ratio: float,
    min_bars: int,
) -> tuple[str, str, str, str]:
    split_idx = int(len(df) * train_ratio)
    if split_idx < min_bars + 10:
        raise ValueError("train split too short for strategy warmup")
    if len(df) - split_idx < min_bars:
        raise ValueError("test split too short for strategy warmup")

    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]
    return (
        _row_date_str(train_df.iloc[0]),
        _row_date_str(train_df.iloc[-1]),
        _row_date_str(test_df.iloc[0]),
        _row_date_str(test_df.iloc[-1]),
    )


def _run_zipline_trial(
    *,
    symbol: str,
    data_dir: str,
    strategy_id: str,
    params: dict[str, Any],
    capital_base: float,
    start: str,
    end: str,
    lookback_days: int,
    timeframe: str,
    force_reingest: bool,
) -> dict[str, Any]:
    return run_zipline_backtest(
        symbol=symbol,
        data_dir=data_dir,
        strategy_id=strategy_id,
        strategy_params=params,
        capital_base=capital_base,
        start=start,
        end=end,
        lookback_days=lookback_days,
        force_reingest=force_reingest,
        timeframe=timeframe,
    )


def run_optuna_tune_sync(
    *,
    symbol: str,
    start: str,
    end: str,
    strategy_id: str,
    n_trials: int = 15,
    train_ratio: float = 0.7,
    capital_base: float = 100_000.0,
    data_dir: str = "data/crypto",
    lookback_days: int = 90,
    timeframe: str = DEFAULT_TIMEFRAME,
    objective: str = "sharpe",
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    sid = strategy_id.strip()
    if sid not in TUNABLE_STRATEGY_IDS:
        raise ValueError(f"strategy not tunable: {strategy_id}")
    if objective not in {"sharpe", "total_return", "calmar"}:
        raise ValueError("objective must be sharpe, total_return, or calmar")
    if not 0.5 <= train_ratio <= 0.9:
        raise ValueError("train_ratio must be between 0.5 and 0.9")
    if n_trials < 3:
        raise ValueError("n_trials must be >= 3")

    spec = get_strategy(sid)
    if not spec:
        raise ValueError(f"unknown strategy: {strategy_id}")
    min_bars = int(spec["min_bars"])
    sym = symbol.strip().upper()
    tf = normalize_timeframe(timeframe)

    df = load_ohlcv_window(
        sym,
        data_dir=data_dir,
        timeframe=tf,
        lookback_days=lookback_days,
        range_start=start,
        range_end=end,
    )
    train_start, train_end, test_start, test_end = compute_train_test_ranges(
        df, train_ratio=train_ratio, min_bars=min_bars
    )

    trial_counter = {"n": 0}
    running_best: dict[str, float | None] = {"v": None}

    def _notify_progress(info: dict[str, Any]) -> None:
        if not progress_cb:
            return
        if running_best["v"] is not None:
            info.setdefault("best_value", running_best["v"])
        progress_cb(info)

    def objective_fn(trial: optuna.Trial) -> float:
        trial_counter["n"] += 1
        try:
            params = suggest_params(trial, sid)
            raw = _run_zipline_trial(
                symbol=sym,
                data_dir=data_dir,
                strategy_id=sid,
                params=params,
                capital_base=capital_base,
                start=train_start,
                end=train_end,
                lookback_days=lookback_days,
                timeframe=tf,
                force_reingest=trial.number == 0,
            )
            score = _metric_value(raw.get("metrics") or {}, objective)
            if running_best["v"] is None or score > running_best["v"]:
                running_best["v"] = score
            _notify_progress(
                {
                    "current_trial": trial_counter["n"],
                    "n_trials": n_trials,
                    "last_params": params,
                    "last_score": score,
                }
            )
            return score
        except (ValueError, RuntimeError):
            _notify_progress(
                {
                    "current_trial": trial_counter["n"],
                    "n_trials": n_trials,
                }
            )
            return -999.0

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective_fn, n_trials=n_trials, show_progress_bar=False)

    best_params = validate_params(sid, study.best_params)
    train_raw = _run_zipline_trial(
        symbol=sym,
        data_dir=data_dir,
        strategy_id=sid,
        params=best_params,
        capital_base=capital_base,
        start=train_start,
        end=train_end,
        lookback_days=lookback_days,
        timeframe=tf,
        force_reingest=False,
    )
    test_raw = _run_zipline_trial(
        symbol=sym,
        data_dir=data_dir,
        strategy_id=sid,
        params=best_params,
        capital_base=capital_base,
        start=test_start,
        end=test_end,
        lookback_days=lookback_days,
        timeframe=tf,
        force_reingest=False,
    )

    run_id = str(uuid.uuid4())
    run_dir = OPTUNA_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    doc = {
        "run_id": run_id,
        "symbol": sym,
        "start": start,
        "end": end,
        "train_start": train_start,
        "train_end": train_end,
        "test_start": test_start,
        "test_end": test_end,
        "strategy_id": sid,
        "strategy_name": spec["name"],
        "timeframe": tf,
        "objective": objective,
        "n_trials": n_trials,
        "train_ratio": train_ratio,
        "best_params": best_params,
        "best_value": study.best_value,
        "train_metrics": dict((train_raw.get("metrics") or {})),
        "test_metrics": dict((test_raw.get("metrics") or {})),
        "created_at": _iso_now(now),
    }
    (run_dir / "best_params.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "run_id": run_id,
        "symbol": sym,
        "strategy_id": sid,
        "strategy_name": spec["name"],
        "timeframe": tf,
        "objective": objective,
        "best_params": best_params,
        "best_value": study.best_value,
        "train_metrics": doc["train_metrics"],
        "test_metrics": doc["test_metrics"],
        "n_trials": n_trials,
        "train_ratio": train_ratio,
        "train_start": train_start,
        "train_end": train_end,
        "test_start": test_start,
        "test_end": test_end,
    }


class CryptoZiplineTuneManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def _save_job(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        run_dir = OPTUNA_DIR / job_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def submit(
        self,
        *,
        symbol: str,
        start: str,
        end: str,
        strategy_id: str,
        n_trials: int = 15,
        train_ratio: float = 0.7,
        capital_base: float = 100_000.0,
        data_dir: str = "data/crypto",
        lookback_days: int = 90,
        timeframe: str = DEFAULT_TIMEFRAME,
        objective: str = "sharpe",
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        job: dict[str, Any] = {
            "job_id": job_id,
            "status": "queued",
            "symbol": symbol.strip().upper(),
            "start": start,
            "end": end,
            "strategy_id": strategy_id,
            "n_trials": n_trials,
            "train_ratio": train_ratio,
            "capital_base": capital_base,
            "data_dir": data_dir,
            "lookback_days": lookback_days,
            "timeframe": normalize_timeframe(timeframe),
            "objective": objective,
            "current_trial": 0,
            "best_value": None,
            "error": None,
            "result": None,
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
        }
        with self._lock:
            self._jobs[job_id] = job
            self._save_job(job_id)

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"crypto-zipline-tune-{job_id[:8]}",
        )
        thread.start()
        return {"job_id": job_id, "status": "queued"}

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["updated_at"] = _iso_now()
            self._save_job(job_id)
            payload = dict(job)

        def progress_cb(info: dict[str, Any]) -> None:
            with self._lock:
                j = self._jobs.get(job_id)
                if not j:
                    return
                j["current_trial"] = info.get("current_trial", j.get("current_trial", 0))
                j["best_value"] = info.get("best_value")
                j["updated_at"] = _iso_now()
                self._save_job(job_id)

        try:
            result = run_optuna_tune_sync(
                symbol=payload["symbol"],
                start=payload["start"],
                end=payload["end"],
                strategy_id=payload["strategy_id"],
                n_trials=int(payload["n_trials"]),
                train_ratio=float(payload["train_ratio"]),
                capital_base=float(payload["capital_base"]),
                data_dir=str(payload["data_dir"]),
                lookback_days=int(payload["lookback_days"]),
                timeframe=str(payload["timeframe"]),
                objective=str(payload["objective"]),
                progress_cb=progress_cb,
            )
            with self._lock:
                j = self._jobs.get(job_id)
                if not j:
                    return
                j["status"] = "completed"
                j["run_id"] = result["run_id"]
                j["result"] = result
                j["best_value"] = result["best_value"]
                j["current_trial"] = j["n_trials"]
                j["updated_at"] = _iso_now()
                self._save_job(job_id)
        except Exception as exc:
            with self._lock:
                j = self._jobs.get(job_id)
                if not j:
                    return
                j["status"] = "failed"
                j["error"] = str(exc)
                j["updated_at"] = _iso_now()
                self._save_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return dict(job)
        path = OPTUNA_DIR / job_id / "job.json"
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        return None


_tune_manager = CryptoZiplineTuneManager()


def get_tune_manager() -> CryptoZiplineTuneManager:
    return _tune_manager


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
