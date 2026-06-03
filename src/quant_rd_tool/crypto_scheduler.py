"""Scheduled crypto data sync + analysis (ccxt incremental → qlib → signals)."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analysis import analyze_crypto_from_df
from quant_rd_tool.crypto_storage import sync_ohlcv

logger = logging.getLogger(__name__)


def run_scheduled_cycle(
    symbols: list[str],
    *,
    data_dir: str | Path = "data/crypto",
    timeframe: str = "5m",
    backfill_days: int = 90,
    with_ml: bool = True,
    ml_algorithm: str = "both",
    exchange_id: cxt.ExchangeId = "binance",
    save_snapshot: bool = True,
    precheck_connectivity: bool = True,
    with_options_vol: bool = True,
    options_iv_after_cycle: bool = True,
) -> list[dict[str, Any]]:
    """Sync incremental OHLCV for each symbol, dump qlib, run technical + ML analysis."""
    if precheck_connectivity and symbols:
        from quant_rd_tool.ccxt_connectivity import require_connectivity

        require_connectivity(
            exchange_id,
            test_ohlcv=True,
            symbol=symbols[0],
            timeframe=timeframe,
        )

    results: list[dict[str, Any]] = []
    for symbol in symbols:
        sym = symbol.strip().upper()
        try:
            df, meta = sync_ohlcv(
                sym,
                data_dir=data_dir,
                timeframe=timeframe,
                backfill_days=backfill_days,
                exchange_id=exchange_id,
            )
            report = analyze_crypto_from_df(
                df,
                sym,
                data_dir=data_dir,
                timeframe=timeframe,
                with_qlib=True,
                with_ml=with_ml,
                ml_algorithm=ml_algorithm,  # type: ignore[arg-type]
                with_options_vol=with_options_vol,
            )
            report["sync"] = meta
            try:
                from quant_rd_tool.crypto_var_schedule import build_var_cycle_fields, var_cycle_needed

                if var_cycle_needed():
                    report.update(build_var_cycle_fields(sym))
            except Exception as ve:
                logger.warning("VaR enrichment skipped for %s: %s", sym, ve)
            if save_snapshot:
                _save_scheduler_snapshot(report, data_dir=data_dir, timeframe=timeframe)
            results.append(report)
            logger.info(
                "Scheduled analysis %s %s: %s bars (+%s), signal=%s",
                sym,
                timeframe,
                meta.get("bars_count", len(df)),
                meta.get("new_bars", 0),
                report.get("combined_signal", {}).get("stance"),
            )
        except Exception as e:
            logger.exception("Scheduled cycle failed for %s", sym)
            results.append(
                {
                    "symbol": sym,
                    "timeframe": timeframe,
                    "error": str(e),
                    "generated_at": datetime.now(UTC).isoformat(),
                }
            )

    if options_iv_after_cycle:
        try:
            from quant_rd_tool.crypto_options_vol_scan import run_options_iv_maintenance

            iv_summary = run_options_iv_maintenance(data_dir=str(data_dir))
            logger.info(
                "Options IV maintenance: elevated=%s bases=%s",
                iv_summary.get("elevated_count"),
                iv_summary.get("elevated_bases"),
            )
        except Exception as e:
            logger.warning("Options IV maintenance failed: %s", e)

    return results


def run_scheduler(
    symbols: list[str],
    *,
    data_dir: str | Path = "data/crypto",
    timeframe: str = "5m",
    interval_minutes: int = 30,
    backfill_days: int = 90,
    with_ml: bool = True,
    ml_algorithm: str = "both",
    exchange_id: cxt.ExchangeId = "binance",
    once: bool = False,
    precheck_connectivity: bool = True,
    with_options_vol: bool = True,
    options_iv_after_cycle: bool = True,
) -> None:
    """Run analysis every ``interval_minutes`` until interrupted (or ``once=True``)."""
    if precheck_connectivity and symbols:
        from quant_rd_tool.ccxt_connectivity import require_connectivity

        require_connectivity(
            exchange_id,
            test_ohlcv=True,
            symbol=symbols[0],
            timeframe=timeframe,
        )

    logger.info(
        "Crypto scheduler started: symbols=%s timeframe=%s interval=%sm once=%s",
        symbols,
        timeframe,
        interval_minutes,
        once,
    )
    while True:
        started = datetime.now(UTC)
        results = run_scheduled_cycle(
            symbols,
            data_dir=data_dir,
            timeframe=timeframe,
            backfill_days=backfill_days,
            with_ml=with_ml,
            ml_algorithm=ml_algorithm,
            exchange_id=exchange_id,
            precheck_connectivity=False,
            with_options_vol=with_options_vol,
            options_iv_after_cycle=options_iv_after_cycle,
        )
        _log_cycle_summary(results, started)
        if once:
            break
        elapsed = (datetime.now(UTC) - started).total_seconds()
        sleep_s = max(interval_minutes * 60 - elapsed, 5)
        logger.info("Next cycle in %.0f seconds", sleep_s)
        time.sleep(sleep_s)


def _save_scheduler_snapshot(
    report: dict[str, Any],
    *,
    data_dir: str | Path,
    timeframe: str,
) -> Path:
    qlib_code = cxt.to_qlib_code(report.get("symbol", "BTC"))
    snap_dir = Path(data_dir) / qlib_code / "scheduler" / timeframe.replace("/", "")
    snap_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = snap_dir / f"{ts}.json"
    payload = {k: v for k, v in report.items() if k != "markdown"}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = snap_dir / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _log_cycle_summary(results: list[dict[str, Any]], started: datetime) -> None:
    lines = []
    for r in results:
        if r.get("error"):
            lines.append(f"{r.get('symbol')}: ERROR {r['error']}")
            continue
        sig = r.get("combined_signal", {})
        sync = r.get("sync", {})
        opt = r.get("options_vol") if isinstance(r.get("options_vol"), dict) else {}
        start, end = format_period_bounds_from_report(r)
        iv_note = ""
        if opt.get("enabled") and opt.get("alert_level") not in (None, "normal"):
            iv_note = f" | IV {opt.get('alert_level')}"
            if opt.get("iv_percentile") is not None:
                iv_note += f" pct={opt.get('iv_percentile')}%"
        lines.append(
            f"{r.get('pair', r.get('symbol'))}: {sig.get('stance')} ({sig.get('action')}) "
            f"+{sync.get('new_bars', 0)} bars{iv_note} | {start} ~ {end}"
        )
    logger.info("Cycle finished in %.1fs\n%s", (datetime.now(UTC) - started).total_seconds(), "\n".join(lines))


def format_period_bounds_from_report(report: dict[str, Any]) -> tuple[str, str]:
    period = report.get("period") or {}
    return period.get("start", ""), period.get("end", "")
