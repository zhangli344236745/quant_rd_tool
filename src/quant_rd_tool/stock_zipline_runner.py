"""A-share backtest runner: zipline via .venv-zipline subprocess or pandas."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

import pandas as pd

from quant_rd_tool.config import _project_root
from quant_rd_tool.crypto_zipline_combo import combo_min_bars, normalize_combo_spec, run_combo_pandas
from quant_rd_tool.crypto_zipline_env import ensure_zipline_venv, zipline_venv_python, zipline_venv_ready
from quant_rd_tool.crypto_zipline_pandas import run_bar_backtest
from quant_rd_tool.crypto_zipline_strategies import get_runner, get_strategy
from quant_rd_tool.crypto_zipline_zipline_engine import _slice_bars_for_backtest
from quant_rd_tool.stock_zipline_bundle import load_ohlcv_window
from quant_rd_tool.stock_zipline_strategies import is_stock_strategy
from quant_rd_tool.stock_zipline_timeframes import DEFAULT_TIMEFRAME, normalize_timeframe

logger = logging.getLogger(__name__)


def zipline_installed() -> tuple[bool, str | None]:
    return zipline_venv_ready()


def run_pandas_backtest(
    df: pd.DataFrame,
    *,
    strategy_id: str,
    strategy_params: dict[str, Any] | None,
    capital_base: float,
    combo_spec: dict[str, Any] | None = None,
    timeframe: str = DEFAULT_TIMEFRAME,
    symbol: str = "600519",
    data_dir: str = "data/stocks",
) -> dict[str, Any]:
    if combo_spec:
        out = run_combo_pandas(df, combo_spec, capital_base)
        out["engine"] = "pandas"
        out["market"] = "stock"
        return out

    spec = get_strategy(strategy_id)
    if not spec:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    if not is_stock_strategy(strategy_id):
        raise ValueError(f"Strategy {strategy_id} is not available for A-share lab")
    params = {**spec["default_params"], **(strategy_params or {})}
    if strategy_id.startswith("xgb_"):
        params["_timeframe"] = normalize_timeframe(timeframe)
    min_bars = int(spec.get("min_bars", 20))
    if len(df) < min_bars:
        raise ValueError(f"Need at least {min_bars} bars, got {len(df)}")
    runner = get_runner(strategy_id)
    if not runner:
        raise ValueError(f"No runner for strategy: {strategy_id}")
    out = runner(df, params, capital_base)
    out["engine"] = "pandas"
    out["strategy_params"] = params
    out["market"] = "stock"
    return out


def run_zipline_subprocess(
    *,
    symbol: str,
    data_dir: str,
    strategy_id: str,
    strategy_params: dict[str, Any] | None,
    capital_base: float,
    start: str,
    end: str,
    lookback_days: int = 365,
    timeout: int = 600,
    force_reingest: bool = False,
    timeframe: str = DEFAULT_TIMEFRAME,
    combo_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    py = zipline_venv_python()
    if not py:
        py = ensure_zipline_venv()
    root = _project_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")

    payload = {
        "symbol": symbol,
        "data_dir": data_dir,
        "strategy_id": strategy_id,
        "strategy_params": strategy_params,
        "capital_base": capital_base,
        "start": start,
        "end": end,
        "lookback_days": lookback_days,
        "force_reingest": force_reingest,
        "timeframe": timeframe,
        "combo_spec": combo_spec,
    }
    proc = subprocess.run(
        [str(py), "-m", "quant_rd_tool.stock_zipline_worker"],
        input=json.dumps(payload, ensure_ascii=False, default=str),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Stock zipline worker failed (code {proc.returncode}):\n{proc.stderr or proc.stdout}"
        )
    return json.loads(proc.stdout)


def run_zipline_backtest(
    *,
    symbol: str,
    data_dir: str,
    strategy_id: str,
    strategy_params: dict[str, Any] | None,
    capital_base: float,
    start: str,
    end: str,
    lookback_days: int = 365,
    force_reingest: bool = False,
    timeframe: str = DEFAULT_TIMEFRAME,
    combo_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ok_venv, _ = zipline_venv_ready()
    kwargs = dict(
        symbol=symbol,
        data_dir=data_dir,
        strategy_id=strategy_id,
        strategy_params=strategy_params,
        capital_base=capital_base,
        start=start,
        end=end,
        lookback_days=lookback_days,
        force_reingest=force_reingest,
        timeframe=timeframe,
        combo_spec=combo_spec,
    )
    if ok_venv:
        return run_zipline_subprocess(**kwargs)
    raise RuntimeError(
        "Zipline venv not ready. Run POST /api/v1/stocks/zipline/setup-venv or use engine=pandas."
    )


def _prepare_backtest_df(
    df: pd.DataFrame,
    *,
    strategy_id: str,
    start: str,
    end: str,
    combo_spec: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if combo_spec:
        warmup = combo_min_bars(combo_spec)
    else:
        spec = get_strategy(strategy_id)
        warmup = int((spec or {}).get("min_bars", 20)) + 5
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    return _slice_bars_for_backtest(df, start=start_ts, end=end_ts, warmup_bars=warmup)


def run_backtest(
    *,
    symbol: str,
    data_dir: str,
    strategy_id: str,
    start: str,
    end: str,
    capital_base: float = 100_000.0,
    strategy_params: dict[str, Any] | None = None,
    lookback_days: int = 365,
    engine: str = "auto",
    force_reingest: bool = False,
    timeframe: str = DEFAULT_TIMEFRAME,
    combo_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tf = normalize_timeframe(timeframe)
    if not is_stock_strategy(strategy_id) and not combo_spec:
        raise ValueError(f"Strategy {strategy_id} is not available for A-share lab")

    if engine == "pandas":
        df = load_ohlcv_window(
            symbol,
            data_dir=data_dir,
            timeframe=tf,
            lookback_days=lookback_days,
            range_start=start,
            range_end=end,
        )
        df = _prepare_backtest_df(
            df, strategy_id=strategy_id, start=start, end=end, combo_spec=combo_spec
        )
        return run_pandas_backtest(
            df,
            strategy_id=strategy_id,
            strategy_params=strategy_params,
            capital_base=capital_base,
            combo_spec=combo_spec,
            timeframe=tf,
            symbol=symbol,
            data_dir=data_dir,
        )

    spec = get_strategy(strategy_id)
    if spec and spec.get("category") == "options":
        raise ValueError(f"Options strategy {strategy_id} is not supported for stocks")

    if strategy_id.startswith("xgb_") and not combo_spec:
        df = load_ohlcv_window(
            symbol,
            data_dir=data_dir,
            timeframe=tf,
            lookback_days=lookback_days,
            range_start=start,
            range_end=end,
        )
        df = _prepare_backtest_df(
            df, strategy_id=strategy_id, start=start, end=end, combo_spec=combo_spec
        )
        out = run_pandas_backtest(
            df,
            strategy_id=strategy_id,
            strategy_params=strategy_params,
            capital_base=capital_base,
            timeframe=tf,
            symbol=symbol,
            data_dir=data_dir,
        )
        out["engine"] = "pandas"
        out["ml_preferred_engine"] = True
        return out

    z_ok, z_err = zipline_installed()
    if engine == "zipline" and not z_ok:
        raise RuntimeError(
            f"zipline-reloaded not available. Use POST /stocks/zipline/setup-venv. Error: {z_err}"
        )

    use_zipline = engine in ("zipline", "auto") and z_ok
    if use_zipline:
        try:
            return run_zipline_backtest(
                symbol=symbol,
                data_dir=data_dir,
                strategy_id=strategy_id,
                strategy_params=strategy_params,
                capital_base=capital_base,
                start=start,
                end=end,
                lookback_days=lookback_days,
                force_reingest=force_reingest,
                timeframe=tf,
                combo_spec=combo_spec,
            )
        except Exception as exc:
            logger.warning("Stock zipline backtest failed, falling back to pandas: %s", exc)
            if engine == "zipline":
                raise

    df = load_ohlcv_window(
        symbol,
        data_dir=data_dir,
        timeframe=tf,
        lookback_days=lookback_days,
        range_start=start,
        range_end=end,
    )
    df = _prepare_backtest_df(
        df, strategy_id=strategy_id, start=start, end=end, combo_spec=combo_spec
    )
    out = run_pandas_backtest(
        df,
        strategy_id=strategy_id,
        strategy_params=strategy_params,
        capital_base=capital_base,
        combo_spec=combo_spec,
        timeframe=tf,
        symbol=symbol,
        data_dir=data_dir,
    )
    out["zipline_fallback_reason"] = z_err if not z_ok else "zipline_run_failed"
    return out
