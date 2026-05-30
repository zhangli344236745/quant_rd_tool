from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def allocate_notional(
    *,
    symbols: list[str],
    total_notional: float,
    max_per_symbol: float,
    max_concurrent_positions: int | None = None,
) -> dict[str, float]:
    """
    Simple equal-weight allocation with caps.

    - Enforces total budget (sum <= total_notional)
    - Enforces per-symbol cap
    - Optionally enforces max_concurrent_positions by allocating to the first N symbols
    """
    syms = [s.strip().upper() for s in symbols if s and s.strip()]
    if not syms or total_notional <= 0 or max_per_symbol <= 0:
        return {s: 0.0 for s in syms}

    if max_concurrent_positions is not None and max_concurrent_positions > 0:
        syms = syms[: int(max_concurrent_positions)]

    n = len(syms)
    if n == 0:
        return {}

    per = float(total_notional) / n
    per = min(per, float(max_per_symbol))

    alloc = {s: float(per) for s in syms}
    # If capping reduced total, still respects total budget.
    return alloc


@dataclass
class PortfolioRunConfig:
    symbols: list[str]
    total_notional_usdt: float = 0.0
    max_per_symbol_notional_usdt: float = 0.0
    max_concurrent_positions: int = 0


def run_portfolio_once(
    bots: dict[str, Any],
    *,
    config: PortfolioRunConfig,
    signal_only: bool = False,
    telemetry: Any | None = None,
) -> dict[str, Any]:
    """
    Minimal portfolio runner (single process):
    - `bots` maps symbol -> an object with `run_once()` method (e.g. BinancePerpBot)
    - returns per-symbol results
    """
    alloc = allocate_notional(
        symbols=config.symbols,
        total_notional=config.total_notional_usdt,
        max_per_symbol=config.max_per_symbol_notional_usdt,
        max_concurrent_positions=(config.max_concurrent_positions or None),
    )
    results: list[dict[str, Any]] = []
    for sym in config.symbols:
        s = sym.strip().upper()
        bot = bots.get(s)
        if not bot:
            results.append({"symbol": s, "skipped": True, "reason": "no bot"})
            continue
        if signal_only and hasattr(bot, "fetch_signal"):
            r = bot.fetch_signal()
        else:
            cap = alloc.get(s, 0.0)
            cap_arg = float(cap) if cap and float(cap) > 0 else None
            r = bot.run_once(portfolio_cap_usdt=cap_arg)
        if isinstance(r, dict):
            r["portfolio_alloc_notional_usdt"] = alloc.get(s, 0.0)
        results.append({"symbol": s, "result": r})
    summary = {"count": len(results), "results": results, "allocation": alloc}
    if telemetry is not None and hasattr(telemetry, "log_portfolio"):
        telemetry.log_portfolio(summary)
    return summary

