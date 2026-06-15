"""Scheduled entry point for A-share announcement radar scans."""

from __future__ import annotations

import logging
from typing import Any

from quant_rd_tool.stock_announcement_radar import run_announcement_scan

logger = logging.getLogger(__name__)


def run_announcement_cycle(
    *,
    data_dir: str = "data/stocks",
    symbols: list[str] | None = None,
    use_watchlist: bool = True,
    job_id: str | None = None,
    min_score: int | None = None,
) -> dict[str, Any]:
    """Run one announcement scan cycle (scheduler job_type=stock_announcements)."""
    kwargs: dict[str, Any] = {
        "data_dir": data_dir,
        "symbols": symbols,
        "use_watchlist": use_watchlist,
    }
    if min_score is not None:
        kwargs["min_score"] = min_score
    result = run_announcement_scan(**kwargs)
    logger.info(
        "Announcement cycle done: scanned=%s new=%s errors=%s",
        result.get("items_processed"),
        result.get("items_new"),
        len(result.get("fetch_errors") or []),
    )
    digest = result.get("digest")
    if digest:
        try:
            from quant_rd_tool.schedule_alerts import evaluate_announcement_alerts

            evaluate_announcement_alerts(job_id or "stock-announcements", digest)
        except Exception:
            logger.debug("Announcement alert evaluation failed", exc_info=True)
    return result
