"""Orchestration for crypto zipline strategy lab."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from quant_rd_tool.config import _project_root
from quant_rd_tool.crypto_storage import sync_ohlcv
from quant_rd_tool.crypto_zipline_bundle import data_status, read_bundle_manifest
from quant_rd_tool.crypto_zipline_combo import normalize_combo_spec
from quant_rd_tool.crypto_zipline_env import zipline_venv_ready
from quant_rd_tool.crypto_zipline_runner import run_backtest
from quant_rd_tool.crypto_zipline_storage import save_run
from quant_rd_tool.crypto_zipline_strategies import list_strategies
from quant_rd_tool.crypto_zipline_timeframes import (
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
    syms = symbols or ["BTC", "ETH"]
    # Main server uses numpy 2; zipline only runs in .venv-zipline subprocess.
    inproc_ok, inproc_err = False, None
    venv_ok, venv_err = zipline_venv_ready()
    z_ok = venv_ok
    engines = ["pandas"]
    if z_ok:
        engines.insert(0, "zipline")

    tf_filter = normalize_timeframe(timeframe) if timeframe else None
    symbol_status: list[dict[str, Any]] = []
    for s in syms:
        if tf_filter:
            symbol_status.append(data_status(s, data_dir=data_dir, timeframe=tf_filter))
        else:
            for tf in SUPPORTED_TIMEFRAMES:
                symbol_status.append(data_status(s, data_dir=data_dir, timeframe=tf))

    return {
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
    data_dir: str = "data/crypto",
    timeframe: str = DEFAULT_TIMEFRAME,
    backfill_days: int = 90,
    exchange_id: str = "binance",
) -> dict[str, Any]:
    tf = normalize_timeframe(timeframe)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for sym in symbols:
        s = sym.strip().upper()
        try:
            _, meta = sync_ohlcv(
                s,
                data_dir=data_dir,
                timeframe=tf,
                backfill_days=backfill_days,
                exchange_id=exchange_id,  # type: ignore[arg-type]
            )
            results.append(meta)
        except Exception as exc:
            errors.append({"symbol": s, "error": str(exc)})
    return {"synced": results, "errors": errors, "timeframe": tf}


def sync_15m(
    symbols: list[str],
    *,
    data_dir: str = "data/crypto",
    backfill_days: int = 90,
    exchange_id: str = "binance",
) -> dict[str, Any]:
    """Backward-compatible alias."""
    return sync_ohlcv_for_lab(
        symbols, data_dir=data_dir, backfill_days=backfill_days, exchange_id=exchange_id
    )


def run_lab_backtest(
    *,
    symbol: str,
    data_dir: str = "data/crypto",
    strategy_id: str,
    start: str,
    end: str,
    capital_base: float = 100_000.0,
    strategy_params: dict[str, Any] | None = None,
    lookback_days: int = 90,
    sync_first: bool = False,
    engine: str = "auto",
    force_reingest: bool = False,
    timeframe: str = DEFAULT_TIMEFRAME,
    strategy_combo: list[dict[str, Any]] | None = None,
    combo_mode: str = "vote",
) -> dict[str, Any]:
    sym = symbol.strip().upper()
    tf = normalize_timeframe(timeframe)
    if sync_first:
        sync_ohlcv_for_lab([sym], data_dir=data_dir, timeframe=tf, backfill_days=lookback_days)

    combo_spec = None
    strategy_label = strategy_id
    if strategy_combo:
        combo_spec = normalize_combo_spec(legs=strategy_combo, mode=combo_mode)
        strategy_label = "combo:" + "+".join(leg["strategy"] for leg in combo_spec["legs"])

    raw = run_backtest(
        symbol=sym,
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
        "symbol": sym,
        "strategy": strategy_label,
        "timeframe": tf,
        "start": start,
        "end": end,
        "capital_base": capital_base,
        "generated_at": datetime.now(UTC).isoformat(),
        **raw,
    }
    if combo_spec:
        result["combo_mode"] = combo_spec["mode"]
        result["combo_legs"] = combo_spec["legs"]
    return save_run(data_dir, result)


def get_strategies() -> list[dict[str, Any]]:
    return list_strategies()
