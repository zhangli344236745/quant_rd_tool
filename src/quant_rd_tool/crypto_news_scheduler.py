"""Scheduled entry point for crypto news scans."""

from __future__ import annotations

import logging
from typing import Any

from quant_rd_tool.crypto_news_config import get_crypto_news_config
from quant_rd_tool.crypto_news_pipeline import run_news_scan

logger = logging.getLogger(__name__)


def run_news_cycle(
    *,
    data_dir: str = "data",
    config: dict[str, Any] | None = None,
    feed_ids: list[str] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Run one news scan cycle (for scheduler job_type=news)."""
    cfg = config or get_crypto_news_config()
    logger.info("Starting crypto news cycle (feeds=%s)", len(cfg.get("feeds") or []))
    result = run_news_scan(data_dir=data_dir, config=cfg, feed_ids=feed_ids)
    logger.info(
        "News cycle done: processed=%s new=%s top=%s",
        result.get("items_processed"),
        result.get("items_new"),
        result.get("top_items"),
    )
    digest = result.get("digest")
    if digest:
        try:
            from quant_rd_tool.schedule_alerts import evaluate_news_alerts

            evaluate_news_alerts(job_id or "crypto-news", digest)
        except Exception:
            logger.debug("News alert evaluation failed", exc_info=True)
    return result
