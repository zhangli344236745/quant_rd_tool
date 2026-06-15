"""Read-only helpers for A-share ops dashboard (freshness, connectivity, schedules)."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool.akshare_data import to_ak_code
from quant_rd_tool.stock_announcement_radar import load_digest
from quant_rd_tool.stock_scheduler import resolve_stock_symbols
from quant_rd_tool.stock_zipline_bundle import data_status


def check_akshare_connectivity(*, probe_code: str = "600519", data_dir: str = "data/stocks") -> dict[str, Any]:
    """Light probe: local CSV or one refresh attempt."""
    from quant_rd_tool.stock_var import fetch_ohlcv_df

    t0 = time.perf_counter()
    code = to_ak_code(probe_code)
    try:
        df = fetch_ohlcv_df(code, data_dir=data_dir, limit=5, refresh=False)
        if len(df) >= 1:
            return {
                "ok": True,
                "probe_code": code,
                "source": "local_cache",
                "bars": len(df),
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        df = fetch_ohlcv_df(code, data_dir=data_dir, limit=5, refresh=True)
        return {
            "ok": len(df) >= 1,
            "probe_code": code,
            "source": "live_fetch",
            "bars": len(df),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    except Exception as e:
        return {
            "ok": False,
            "probe_code": code,
            "error": str(e),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }


def scan_data_freshness(
    *,
    data_dir: str = "data/stocks",
    symbols: list[str] | None = None,
    use_watchlist: bool = True,
    stale_calendar_days: int = 5,
) -> dict[str, Any]:
    """Report OHLCV last bar age for watchlist / configured symbols."""
    codes = resolve_stock_symbols(symbols or [], use_watchlist=use_watchlist)
    today = date.today()
    items: list[dict[str, Any]] = []
    stale_count = 0
    for code in codes:
        st = data_status(code, data_dir=data_dir, timeframe="1d")
        last_bar = st.get("last_bar")
        days_old: int | None = None
        stale = False
        if last_bar:
            try:
                last_dt = datetime.strptime(str(last_bar)[:10], "%Y-%m-%d").date()
                days_old = (today - last_dt).days
                stale = days_old > stale_calendar_days
            except ValueError:
                stale = True
        else:
            stale = True
        if stale:
            stale_count += 1
        items.append(
            {
                "code": code,
                "symbol": st.get("symbol"),
                "ready": st.get("ready"),
                "bars_count": st.get("bars_count"),
                "last_bar": last_bar,
                "days_old": days_old,
                "stale": stale,
            }
        )
    return {
        "symbols_checked": len(items),
        "stale_count": stale_count,
        "stale_calendar_days": stale_calendar_days,
        "checked_at": datetime.now(UTC).isoformat(),
        "items": items,
    }


def build_stock_ops_summary(
    *,
    data_dir: str = "data/stocks",
    stale_calendar_days: int = 5,
) -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager
    from quant_rd_tool.schedule_alerts import evaluate_stale_jobs, get_alert_rules, tail_alert_log

    mgr = get_scheduler_manager(data_dir)
    jobs = mgr.list_jobs()
    running = sum(1 for j in jobs if j.get("status") == "running")
    connectivity = check_akshare_connectivity(data_dir=data_dir)
    freshness = scan_data_freshness(data_dir=data_dir, use_watchlist=True, stale_calendar_days=stale_calendar_days)
    digest = load_digest(data_dir)
    stale_fired = evaluate_stale_jobs(jobs)
    return {
        "market": "stock",
        "data_dir": data_dir,
        "connectivity": connectivity,
        "data_freshness": freshness,
        "announcements": {
            "digest_generated_at": digest.get("generated_at"),
            "items_new": digest.get("items_new"),
            "symbols_scanned": digest.get("symbols_scanned"),
            "top_items": (digest.get("top_items") or [])[:10],
            "errors": digest.get("errors") or [],
        },
        "schedules": {
            "total": len(jobs),
            "running": running,
            "jobs": jobs,
        },
        "schedule_alerts": get_alert_rules(),
        "schedule_alert_recent": tail_alert_log(limit=20),
        "schedule_stale_checks": stale_fired,
    }
