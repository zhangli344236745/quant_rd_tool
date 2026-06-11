"""A-share zipline strategy catalog (shared TV/ML registry, minus crypto options)."""

from __future__ import annotations

from typing import Any

from quant_rd_tool.crypto_zipline_strategies import get_strategy, list_strategies

_STOCK_EXCLUDED_CATEGORIES = frozenset({"options"})
_STOCK_EXCLUDED_PREFIXES = ("opt_",)


def is_stock_strategy(strategy_id: str) -> bool:
    sid = (strategy_id or "").strip()
    if sid.startswith(_STOCK_EXCLUDED_PREFIXES):
        return False
    spec = get_strategy(sid)
    if spec and spec.get("category") in _STOCK_EXCLUDED_CATEGORIES:
        return False
    return bool(spec)


def list_stock_strategies() -> list[dict[str, Any]]:
    """Return strategies applicable to A-share daily lab (no Binance options)."""
    out: list[dict[str, Any]] = []
    for spec in list_strategies():
        sid = spec["id"]
        if sid.startswith(_STOCK_EXCLUDED_PREFIXES):
            continue
        if spec.get("category") in _STOCK_EXCLUDED_CATEGORIES:
            continue
        out.append(spec)
    return out
