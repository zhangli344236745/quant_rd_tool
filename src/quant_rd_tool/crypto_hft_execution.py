"""Shared execution helpers for REST and WebSocket crypto market-making."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from quant_rd_tool.crypto_hft_common import ReconcilePlan, plan_reconcile, price_within_tolerance, summarize_book
from quant_rd_tool.crypto_hft_strategies import Quote

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"mm-([a-zA-Z0-9_-]+)$")


class MmBotConfig(Protocol):
    bot_id: str
    post_only: bool
    max_order_size_usdt: float
    price_tolerance_bps: float
    maker_fee_bps: float
    min_edge_bps: float
    use_client_order_tags: bool
    batch_cancel: bool
    market_type: str


@dataclass
class ExecutionPrepStats:
    rejected_cross: int = 0
    fee_adjusted: int = 0


def default_execution_stats() -> dict[str, Any]:
    return {
        "placed": 0,
        "canceled": 0,
        "rejected_cross": 0,
        "fee_adjusted": 0,
        "batch_cancel_used": 0,
        "reconnects": 0,
    }


def client_order_id(bot_id: str, tag: str) -> str:
    safe_tag = re.sub(r"[^a-zA-Z0-9_-]", "", tag or "q")[:24]
    safe_bot = re.sub(r"[^a-zA-Z0-9_-]", "", bot_id)[:16]
    # Binance clientOrderId max 36 chars
    return f"mm-{safe_bot}-{safe_tag}"[:36]


def extract_order_tag(order: dict[str, Any]) -> str | None:
    cid = str(order.get("clientOrderId") or order.get("client_order_id") or "")
    m = _TAG_RE.search(cid)
    if m:
        return m.group(1)
    info = order.get("info") or {}
    cid2 = str(info.get("clientOrderId") or info.get("origClientOrderId") or "")
    m2 = _TAG_RE.search(cid2)
    return m2.group(1) if m2 else None


def min_half_spread_bps(maker_fee_bps: float, min_edge_bps: float) -> float:
    return float(maker_fee_bps) + float(min_edge_bps)


def prepare_quotes(
    quotes: list[Quote],
    book: dict[str, Any],
    *,
    maker_fee_bps: float = 2.0,
    min_edge_bps: float = 1.0,
) -> tuple[list[Quote], ExecutionPrepStats]:
    """Filter crossing quotes and widen toward fee-aware minimum half-spread."""
    summary = summarize_book(book)
    best_bid = summary.get("best_bid")
    best_ask = summary.get("best_ask")
    mid = summary.get("mid")
    stats = ExecutionPrepStats()
    if not mid or mid <= 0:
        return quotes, stats

    half_ratio = min_half_spread_bps(maker_fee_bps, min_edge_bps) / 10_000.0
    out: list[Quote] = []

    for q in quotes:
        px = q.price
        if q.side == "buy":
            if best_ask is not None and px >= best_ask:
                stats.rejected_cross += 1
                continue
            floor_px = mid * (1.0 - half_ratio)
            if px > floor_px:
                px = floor_px
                stats.fee_adjusted += 1
        else:
            if best_bid is not None and px <= best_bid:
                stats.rejected_cross += 1
                continue
            ceil_px = mid * (1.0 + half_ratio)
            if px < ceil_px:
                px = ceil_px
                stats.fee_adjusted += 1
        if px <= 0:
            stats.rejected_cross += 1
            continue
        if abs(px - q.price) > 1e-12:
            q = Quote(side=q.side, price=round(px, 8), amount=q.amount, level=q.level, tag=q.tag)
        out.append(q)
    return out, stats


def plan_reconcile_tagged(
    open_orders: list[dict[str, Any]],
    desired: list[Quote],
    *,
    tolerance_bps: float,
    bot_id: str,
    use_tags: bool = True,
) -> ReconcilePlan:
    if not use_tags:
        return plan_reconcile(open_orders, desired, tolerance_bps=tolerance_bps)

    unmatched_open = list(open_orders)
    to_place: list[Quote] = []
    to_cancel: list[dict[str, Any]] = []

    for quote in desired:
        expected_cid = client_order_id(bot_id, quote.tag or quote.side)
        match = None
        for o in unmatched_open:
            if str(o.get("side", "")).lower() != quote.side:
                continue
            cid = str(o.get("clientOrderId") or (o.get("info") or {}).get("clientOrderId") or "")
            if cid == expected_cid:
                match = o
                break
        if match is None:
            for o in unmatched_open:
                if str(o.get("side", "")).lower() != quote.side:
                    continue
                px = float(o.get("price") or 0)
                if price_within_tolerance(px, quote.price, tolerance_bps):
                    match = o
                    break
        if match:
            unmatched_open.remove(match)
        else:
            to_place.append(quote)

    to_cancel.extend(unmatched_open)
    return ReconcilePlan(cancel=to_cancel, place=to_place)


def build_limit_order_params(cfg: MmBotConfig, quote: Quote) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if cfg.post_only:
        params["postOnly"] = True
    if cfg.market_type == "future":
        params["reduceOnly"] = False
    if cfg.use_client_order_tags:
        params["clientOrderId"] = client_order_id(cfg.bot_id, quote.tag or quote.side)
    return params


def cancel_orders_batch(ex: Any, symbol: str, orders: list[dict[str, Any]], *, batch: bool = True) -> int:
    if not orders:
        return 0
    ids = [str(o["id"]) for o in orders if o.get("id")]
    if not ids:
        return 0
    if batch and hasattr(ex, "cancel_orders"):
        try:
            ex.cancel_orders(ids, symbol)
            return len(ids)
        except Exception as e:  # noqa: BLE001
            logger.warning("batch cancel failed, falling back: %s", e)
    n = 0
    for oid in ids:
        try:
            ex.cancel_order(oid, symbol)
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("cancel failed %s: %s", oid, e)
    return n


async def cancel_orders_batch_async(
    ex: Any, symbol: str, orders: list[dict[str, Any]], *, batch: bool = True
) -> int:
    if not orders:
        return 0
    ids = [str(o["id"]) for o in orders if o.get("id")]
    if not ids:
        return 0
    if batch and hasattr(ex, "cancel_orders"):
        try:
            await ex.cancel_orders(ids, symbol)
            return len(ids)
        except Exception as e:  # noqa: BLE001
            logger.warning("batch cancel failed, falling back: %s", e)
    n = 0
    for oid in ids:
        try:
            await ex.cancel_order(oid, symbol)
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("cancel failed %s: %s", oid, e)
    return n


def bump_execution_stats(state: dict[str, Any], **kwargs: Any) -> None:
    stats = dict(state.get("execution_stats") or default_execution_stats())
    for k, v in kwargs.items():
        if k in stats and isinstance(stats[k], (int, float)):
            stats[k] = type(stats[k])(stats[k]) + v
        else:
            stats[k] = v
    state["execution_stats"] = stats
