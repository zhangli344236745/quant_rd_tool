"""Scheduled scan cycle for Polymarket binary arbitrage."""

from __future__ import annotations

from typing import Any

from quant_rd_tool.crypto_polymarket_arb import (
    evaluate_polymarket_alerts,
    load_config,
    scan_markets,
)


def run_polymarket_scan_cycle(*, force: bool = False) -> dict[str, Any]:
    cfg = load_config()
    scan = scan_markets(cfg, force=force)
    alerts = evaluate_polymarket_alerts(scan, cfg)
    return {
        "scan": scan,
        "alerts_fired": len(alerts),
        "alerts": alerts,
        "markets_scanned": scan.get("markets_scanned"),
        "opportunities_count": scan.get("opportunities_count"),
        "best_edge_bps": scan.get("best_edge_bps"),
    }


def summarize_polymarket_cycle(result: dict[str, Any]) -> dict[str, Any]:
    scan = result.get("scan") or result
    return {
        "markets_scanned": scan.get("markets_scanned", 0),
        "opportunities_count": scan.get("opportunities_count", 0),
        "best_edge_bps": scan.get("best_edge_bps"),
        "alerts_fired": result.get("alerts_fired", 0),
        "errors": scan.get("errors", 0),
    }
