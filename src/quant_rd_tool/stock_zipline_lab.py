"""Orchestration for A-share zipline strategy lab."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from quant_rd_tool import akshare_data as ak_data
from quant_rd_tool import market_data as mkt
from quant_rd_tool.config import _project_root
from quant_rd_tool.crypto_zipline_combo import normalize_combo_spec
from quant_rd_tool.crypto_zipline_env import zipline_venv_ready
from quant_rd_tool.crypto_zipline_storage import save_run
from quant_rd_tool.crypto_zipline_strategies import list_strategies
from quant_rd_tool.stock_storage import csv_path, save_csv, stock_root, write_meta
from quant_rd_tool.stock_zipline_bundle import data_status, read_bundle_manifest
from quant_rd_tool.stock_zipline_runner import run_backtest
from quant_rd_tool.stock_zipline_timeframes import (
    DEFAULT_TIMEFRAME,
    SUPPORTED_TIMEFRAMES,
    list_timeframe_options,
    normalize_timeframe,
)


def lab_status(
    data_dir: str,
    symbols: list[str] | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    syms = symbols or ["600519", "000001"]
    inproc_ok, inproc_err = False, None
    venv_ok, venv_err = zipline_venv_ready()
    z_ok = venv_ok
    engines = ["pandas"]
    if z_ok:
        engines.insert(0, "zipline")

    tf_filter = normalize_timeframe(timeframe) if timeframe else None
    symbol_status: list[dict[str, Any]] = []
    for s in syms:
        code = ak_data.to_ak_code(s)
        if tf_filter:
            symbol_status.append(data_status(code, data_dir=data_dir, timeframe=tf_filter))
        else:
            for tf in SUPPORTED_TIMEFRAMES:
                symbol_status.append(data_status(code, data_dir=data_dir, timeframe=tf))

    return {
        "market": "stock",
        "timeframes": list_timeframe_options(),
        "default_timeframe": DEFAULT_TIMEFRAME,
        "zipline_installed": z_ok,
        "zipline_inprocess": inproc_ok,
        "zipline_venv": venv_ok,
        "zipline_error": inproc_err if not inproc_ok else (venv_err if not venv_ok else None),
        "zipline_venv_path": str(_project_root() / ".venv-zipline"),
        "engines": engines,
        "default_engine": "zipline" if z_ok else "pandas",
        "combo_modes": ["vote", "and", "or", "weighted"],
        "bundle_cache": read_bundle_manifest(data_dir),
        "symbols": symbol_status,
    }


def sync_ohlcv_for_lab(
    symbols: list[str],
    *,
    data_dir: str = "data/stocks",
    backfill_days: int = 800,
) -> dict[str, Any]:
    """Fetch daily OHLCV via akshare/openbb and persist ohlcv.csv (no full qlib analyze)."""
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=backfill_days)).isoformat()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for sym in symbols:
        raw = sym.strip()
        if not raw:
            continue
        code = ak_data.to_ak_code(raw)
        qlib_code = ak_data.to_qlib_code(raw)
        try:
            df = mkt.fetch_stock_daily(code, start_date=start_date, end_date=end_date)
            root = stock_root(data_dir, code)
            path = csv_path(root)
            save_csv(df, path)
            write_meta(
                root,
                {
                    "symbol": qlib_code,
                    "start_date": start_date,
                    "end_date": end_date,
                    "source": "lab_sync",
                    "bars": len(df),
                },
            )
            results.append(
                {
                    "symbol": qlib_code,
                    "code": code,
                    "bars_count": len(df),
                    "last_bar": str(df.iloc[-1]["date"]) if len(df) else None,
                    "path": str(path),
                }
            )
        except Exception as exc:
            errors.append({"symbol": code, "error": str(exc)})
    return {"synced": results, "errors": errors, "timeframe": DEFAULT_TIMEFRAME}


def run_lab_backtest(
    *,
    symbol: str,
    data_dir: str = "data/stocks",
    strategy_id: str,
    start: str,
    end: str,
    capital_base: float = 100_000.0,
    strategy_params: dict[str, Any] | None = None,
    lookback_days: int = 800,
    sync_first: bool = False,
    engine: str = "auto",
    force_reingest: bool = False,
    timeframe: str = DEFAULT_TIMEFRAME,
    strategy_combo: list[dict[str, Any]] | None = None,
    combo_mode: str = "vote",
) -> dict[str, Any]:
    code = ak_data.to_ak_code(symbol.strip())
    tf = normalize_timeframe(timeframe)
    if sync_first:
        sync_ohlcv_for_lab([code], data_dir=data_dir, backfill_days=lookback_days)

    combo_spec = None
    strategy_label = strategy_id
    if strategy_combo:
        combo_spec = normalize_combo_spec(legs=strategy_combo, mode=combo_mode)
        strategy_label = "combo:" + "+".join(leg["strategy"] for leg in combo_spec["legs"])

    raw = run_backtest(
        symbol=code,
        data_dir=data_dir,
        strategy_id=strategy_id,
        start=start,
        end=end,
        capital_base=capital_base,
        strategy_params=strategy_params,
        lookback_days=lookback_days,
        engine=engine,
        force_reingest=force_reingest,
        timeframe=tf,
        combo_spec=combo_spec,
    )
    result = {
        "run_id": str(uuid.uuid4()),
        "symbol": ak_data.to_qlib_code(code),
        "code": code,
        "strategy": strategy_label,
        "timeframe": tf,
        "start": start,
        "end": end,
        "capital_base": capital_base,
        "market": "stock",
        "generated_at": datetime.now(UTC).isoformat(),
        **raw,
    }
    if combo_spec:
        result["combo_mode"] = combo_spec["mode"]
        result["combo_legs"] = combo_spec["legs"]
    return save_run(data_dir, result)


def get_strategies() -> list[dict[str, Any]]:
    return list_strategies()
