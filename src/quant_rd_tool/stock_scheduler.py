"""Scheduled A-share qlib analysis (watchlist or symbol list → report refresh)."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool.akshare_data import to_ak_code

logger = logging.getLogger(__name__)


def resolve_stock_symbols(
    symbols: list[str],
    *,
    use_watchlist: bool = False,
) -> list[str]:
    """Return ak-style codes to analyze."""
    if use_watchlist:
        from quant_rd_tool.watchlist import Watchlist

        items = Watchlist().list_items()
        codes = [str(it.get("code") or "").strip() for it in items if it.get("code")]
        if codes:
            return [to_ak_code(c) for c in codes]
    return [to_ak_code(s) for s in symbols if str(s).strip()]


def run_stock_scheduled_cycle(
    symbols: list[str],
    *,
    data_dir: str | Path = "data/stocks",
    years: int = 2,
    with_ml: bool = True,
    ml_algorithm: str = "both",
    with_openbb: bool = False,
    refresh: bool = True,
    use_watchlist: bool = False,
    save_snapshot: bool = True,
) -> list[dict[str, Any]]:
    """Run qlib analysis for each A-share symbol; returns per-symbol result dicts."""
    from quant_rd_tool.akshare_stocks import run_qlib_stock_analysis

    codes = resolve_stock_symbols(symbols, use_watchlist=use_watchlist)
    if not codes:
        return [
            {
                "symbol": "",
                "code": "",
                "error": "无分析标的（请配置 symbols 或启用自选列表）",
                "generated_at": now_iso(),
            }
        ]

    results: list[dict[str, Any]] = []
    for code in codes:
        try:
            out = run_qlib_stock_analysis(
                code,
                years=years,
                refresh=refresh,
                data_dir=str(data_dir),
                with_ml=with_ml,
                ml_algorithm=ml_algorithm,
                with_openbb_enrichment=with_openbb,
            )
            report = out.get("report") if isinstance(out.get("report"), dict) else {}
            narrative = report.get("narrative") if isinstance(report.get("narrative"), dict) else {}
            summary = out.get("summary") if isinstance(out.get("summary"), dict) else {}
            entry: dict[str, Any] = {
                "code": out.get("code", code),
                "symbol": out.get("qlib_code") or report.get("symbol") or code,
                "years": years,
                "summary": summary,
                "narrative": narrative,
                "generated_at": out.get("generated_at") or report.get("generated_at"),
            }
            if save_snapshot and report:
                entry["snapshot"] = str(
                    _save_scheduler_snapshot(report, data_dir=data_dir, code=code)
                )
            results.append(entry)
            logger.info(
                "Stock scheduled analysis %s: stance=%s",
                code,
                narrative.get("stance") or summary.get("stance"),
            )
        except Exception as e:
            logger.exception("Stock scheduled cycle failed for %s", code)
            results.append(
                {
                    "code": code,
                    "symbol": code,
                    "error": str(e),
                    "generated_at": now_iso(),
                }
            )
    return results


def _save_scheduler_snapshot(
    report: dict[str, Any],
    *,
    data_dir: str | Path,
    code: str,
) -> Path:
    from quant_rd_tool.akshare_data import to_qlib_code

    qlib_code = to_qlib_code(report.get("symbol") or code)
    snap_dir = Path(data_dir) / qlib_code / "scheduler" / "1d"
    snap_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = snap_dir / f"{ts}.json"
    payload = {k: v for k, v in report.items() if k != "markdown"}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = snap_dir / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
