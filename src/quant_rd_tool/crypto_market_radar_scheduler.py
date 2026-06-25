"""Scan cycle wrapper for crypto market radar."""

from __future__ import annotations

from typing import Any

from quant_rd_tool.crypto_market_radar import load_config, scan_markets


def run_market_radar_scan_cycle(*, force: bool = False) -> dict[str, Any]:
    cfg = load_config()
    return scan_markets(cfg, force=force)


def summarize_market_radar_cycle(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "binance_new_count": result.get("binance_new_count", 0),
        "coingecko_new_count": result.get("coingecko_new_count", 0),
        "high_volatility_flagged_count": result.get("high_volatility_flagged_count", 0),
        "alerts_count": len(result.get("alerts") or []),
        "duration_sec": result.get("duration_sec"),
    }
