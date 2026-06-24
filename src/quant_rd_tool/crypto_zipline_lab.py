"""Orchestration for crypto zipline strategy lab."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

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
    with_options_context: bool = False,
    with_options_backtest: bool = False,
    options_overlay: str = "auto",
    options_backtest_params: dict[str, Any] | None = None,
    commission_pct: float | None = None,
    slippage_pct: float | None = None,
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
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
    )
    result = {
        "run_id": str(uuid.uuid4()),
        "symbol": sym,
        "strategy": strategy_label,
        "timeframe": tf,
        "start": start,
        "end": end,
        "capital_base": capital_base,
        "generated_at": now_iso(),
        **raw,
    }
    if combo_spec:
        result["combo_mode"] = combo_spec["mode"]
        result["combo_legs"] = combo_spec["legs"]
    if with_options_backtest and not (raw.get("options_backtest") or {}).get("enabled"):
        from quant_rd_tool.crypto_options_backtest import attach_options_overlay_to_result
        from quant_rd_tool.crypto_zipline_bundle import load_ohlcv_window
        from quant_rd_tool.crypto_zipline_runner import _prepare_backtest_df, run_pandas_backtest

        try:
            odf = load_ohlcv_window(
                sym,
                data_dir=data_dir,
                timeframe=tf,
                lookback_days=lookback_days,
                range_start=start,
                range_end=end,
            )
            odf = _prepare_backtest_df(
                odf,
                strategy_id=strategy_id,
                start=start,
                end=end,
                combo_spec=combo_spec,
            )
            curve = result.get("equity_curve") or []
            needs_targets = not curve or all(pt.get("target") is None for pt in curve)
            if needs_targets:
                sig_bt = run_pandas_backtest(
                    odf,
                    strategy_id=strategy_id,
                    strategy_params=strategy_params,
                    capital_base=capital_base,
                    combo_spec=combo_spec,
                    timeframe=tf,
                    symbol=sym,
                    data_dir=data_dir,
                )
                sig_curve = sig_bt.get("equity_curve") or []
                for i, pt in enumerate(curve):
                    if i < len(sig_curve) and sig_curve[i].get("target") is not None:
                        pt["target"] = sig_curve[i]["target"]
            attach_options_overlay_to_result(
                result,
                symbol=sym,
                data_dir=data_dir,
                df=odf,
                overlay_id=options_overlay,  # type: ignore[arg-type]
                params=options_backtest_params,
            )
        except Exception as e:
            result["options_backtest"] = {"enabled": False, "error": str(e)}

    if with_options_context:
        from quant_rd_tool.crypto_options_integration import fetch_options_context
        from quant_rd_tool.crypto_options_strategies import build_strategy_pack

        try:
            from quant_rd_tool.crypto_options_strike_probs import build_strike_probability_report

            opts = fetch_options_context(sym, data_dir=data_dir, persist_snapshot=False)
            if opts.get("enabled"):
                scan_item = opts.get("scan_item") or {}
                try:
                    ladder = build_strike_probability_report(
                        sym,
                        n=3,
                        data_dir=data_dir,
                        expiry_iso=scan_item.get("expiry"),
                        with_purchase_advice=False,
                    )
                    opts["strike_ladder"] = ladder
                except Exception:
                    pass
                opts["strategy_pack"] = build_strategy_pack(
                    scan_item=scan_item,
                    strike_report=opts.get("strike_ladder"),
                    spot_stance="中性",
                )
            result["options_context"] = opts
        except Exception as e:
            result["options_context"] = {"enabled": False, "error": str(e)}

    if with_options_backtest or with_options_context:
        from quant_rd_tool.crypto_options_portfolio_greeks import attach_portfolio_greeks_to_result

        attach_portfolio_greeks_to_result(result, symbol=sym, capital=capital_base)

    return save_run(data_dir, result)


def get_strategies() -> list[dict[str, Any]]:
    return list_strategies()
