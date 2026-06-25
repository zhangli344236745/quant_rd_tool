"""Polymarket arbitrage strategy evaluators."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quant_rd_tool.crypto_polymarket_arb import PolymarketArbConfig

REFERENCE_PROFIT_SHARES = 100.0


def _opportunity_gate(
    edge_bps: float,
    fillable: float,
    liquidity_usd: float,
    config: PolymarketArbConfig,
) -> bool:
    return (
        edge_bps >= config.min_edge_bps
        and fillable >= config.min_size_shares
        and liquidity_usd >= config.min_liquidity_usd
    )


def _profit_fields(edge: float, fillable: float, cost_per_share: float) -> dict[str, Any]:
    ref = min(REFERENCE_PROFIT_SHARES, fillable) if fillable > 0 else 0.0
    profit_usd = edge * fillable if edge > 0 and fillable > 0 else 0.0
    cost_at_ref = ref * cost_per_share
    profit_at_ref = edge * ref if edge > 0 and ref > 0 else 0.0
    roi = (profit_at_ref / cost_at_ref * 100.0) if cost_at_ref > 0 and profit_at_ref > 0 else 0.0
    return {
        "profit_usd": round(profit_usd, 4),
        "ref_shares": round(ref, 4),
        "cost_at_100_usd": round(cost_at_ref, 4),
        "profit_at_100_usd": round(profit_at_ref, 4),
        "roi_at_100_pct": round(roi, 2),
    }


def eval_binary_ask(
    *,
    ask_yes: float,
    ask_no: float,
    ask_yes_size: float,
    ask_no_size: float,
    depth: dict[str, Any] | None,
    config: PolymarketArbConfig,
) -> dict[str, Any]:
    fee_yes = ask_yes * config.taker_fee_bps / 10_000.0
    fee_no = ask_no * config.taker_fee_bps / 10_000.0
    raw_edge = 1.0 - ask_yes - ask_no
    edge = raw_edge - fee_yes - fee_no
    size_cap = min(float(ask_yes_size), float(ask_no_size))
    edge_bps = edge * 10_000.0
    liquidity_usd = ask_yes * ask_yes_size + ask_no * ask_no_size

    vwap_yes = ask_yes
    vwap_no = ask_no
    fillable = size_cap
    depth_levels = 1
    edge_at_size = edge
    if depth and depth.get("fillable_shares", 0) > 0:
        vwap_yes = float(depth.get("vwap_yes") or ask_yes)
        vwap_no = float(depth.get("vwap_no") or ask_no)
        fillable = float(depth.get("fillable_shares") or 0)
        depth_levels = int(depth.get("depth_levels") or 1)
        fee_y = vwap_yes * config.taker_fee_bps / 10_000.0
        fee_n = vwap_no * config.taker_fee_bps / 10_000.0
        edge_at_size = 1.0 - vwap_yes - vwap_no - fee_y - fee_n

    edge_at_size_bps = edge_at_size * 10_000.0
    use_depth = config.use_depth_for_opportunity
    gate_edge = edge_at_size_bps if use_depth else edge_bps
    gate_fill = fillable if use_depth else size_cap
    opportunity = _opportunity_gate(gate_edge, gate_fill, liquidity_usd, config)
    slippage_bps = round(edge_at_size_bps - edge_bps, 2)
    profit_at_size = edge_at_size * min(config.depth_target_shares, fillable) if edge_at_size > 0 else 0.0

    out: dict[str, Any] = {
        "strategy_type": "binary_ask",
        "ask_yes": round(ask_yes, 6),
        "ask_no": round(ask_no, 6),
        "ask_yes_size": round(ask_yes_size, 4),
        "ask_no_size": round(ask_no_size, 4),
        "raw_edge": round(raw_edge, 6),
        "fee_yes": round(fee_yes, 6),
        "fee_no": round(fee_no, 6),
        "edge": round(edge, 6),
        "edge_bps": round(edge_bps, 2),
        "size_cap": round(size_cap, 4),
        "liquidity_usd": round(liquidity_usd, 2),
        "vwap_yes": round(vwap_yes, 6),
        "vwap_no": round(vwap_no, 6),
        "fillable_shares": round(fillable, 4),
        "depth_levels": depth_levels,
        "edge_at_size": round(edge_at_size, 6),
        "edge_at_size_bps": round(edge_at_size_bps, 2),
        "slippage_bps": slippage_bps,
        "profit_at_size_usd": round(profit_at_size, 4),
        "opportunity": opportunity,
        "paper_tradable": True,
    }
    out.update(_profit_fields(edge, size_cap, ask_yes + ask_no))
    if depth:
        out["yes_ladder"] = depth.get("yes_ladder")
        out["no_ladder"] = depth.get("no_ladder")
    return out


def eval_binary_bid(
    *,
    bid_yes: float,
    bid_no: float,
    bid_yes_size: float,
    bid_no_size: float,
    depth: dict[str, Any] | None,
    config: PolymarketArbConfig,
) -> dict[str, Any]:
    fee_yes = bid_yes * config.taker_fee_bps / 10_000.0
    fee_no = bid_no * config.taker_fee_bps / 10_000.0
    raw_edge = bid_yes + bid_no - 1.0
    edge = raw_edge - fee_yes - fee_no
    size_cap = min(float(bid_yes_size), float(bid_no_size))
    edge_bps = edge * 10_000.0
    liquidity_usd = bid_yes * bid_yes_size + bid_no * bid_no_size

    vwap_yes = bid_yes
    vwap_no = bid_no
    fillable = size_cap
    depth_levels = 1
    edge_at_size = edge
    if depth and depth.get("fillable_shares", 0) > 0:
        vwap_yes = float(depth.get("vwap_bid_yes") or bid_yes)
        vwap_no = float(depth.get("vwap_bid_no") or bid_no)
        fillable = float(depth.get("fillable_shares") or 0)
        depth_levels = int(depth.get("depth_levels") or 1)
        fee_y = vwap_yes * config.taker_fee_bps / 10_000.0
        fee_n = vwap_no * config.taker_fee_bps / 10_000.0
        edge_at_size = vwap_yes + vwap_no - 1.0 - fee_y - fee_n

    edge_at_size_bps = edge_at_size * 10_000.0
    use_depth = config.use_depth_for_opportunity
    gate_edge = edge_at_size_bps if use_depth else edge_bps
    gate_fill = fillable if use_depth else size_cap
    opportunity = _opportunity_gate(gate_edge, gate_fill, liquidity_usd, config)
    slippage_bps = round(edge_at_size_bps - edge_bps, 2)
    profit_at_size = edge_at_size * min(config.depth_target_shares, fillable) if edge_at_size > 0 else 0.0

    out: dict[str, Any] = {
        "strategy_type": "binary_bid",
        "bid_yes": round(bid_yes, 6),
        "bid_no": round(bid_no, 6),
        "bid_yes_size": round(bid_yes_size, 4),
        "bid_no_size": round(bid_no_size, 4),
        "raw_edge": round(raw_edge, 6),
        "edge": round(edge, 6),
        "edge_bps": round(edge_bps, 2),
        "size_cap": round(size_cap, 4),
        "liquidity_usd": round(liquidity_usd, 2),
        "vwap_bid_yes": round(vwap_yes, 6),
        "vwap_bid_no": round(vwap_no, 6),
        "fillable_shares": round(fillable, 4),
        "depth_levels": depth_levels,
        "edge_at_size": round(edge_at_size, 6),
        "edge_at_size_bps": round(edge_at_size_bps, 2),
        "slippage_bps": slippage_bps,
        "profit_at_size_usd": round(profit_at_size, 4),
        "opportunity": opportunity,
        "paper_tradable": False,
    }
    out.update(_profit_fields(edge, size_cap, 2.0 - bid_yes - bid_no))
    if depth:
        out["yes_ladder"] = depth.get("yes_ladder")
        out["no_ladder"] = depth.get("no_ladder")
    return out


def eval_multi_ask(
    *,
    vwaps: list[float],
    sizes: list[float],
    outcomes: list[str],
    depth: dict[str, Any] | None,
    config: PolymarketArbConfig,
) -> dict[str, Any]:
    if len(vwaps) < config.min_outcomes_multi:
        return {"strategy_type": "multi_ask", "opportunity": False, "paper_tradable": False}

    top_sum = sum(vwaps)
    fee = sum(v * config.taker_fee_bps / 10_000.0 for v in vwaps)
    raw_edge = 1.0 - top_sum
    edge = raw_edge - fee
    edge_bps = edge * 10_000.0
    size_cap = min(sizes) if sizes else 0.0
    liquidity_usd = sum(v * s for v, s in zip(vwaps, sizes, strict=False))

    fillable = size_cap
    depth_levels = 1
    edge_at_size = edge
    if depth and depth.get("fillable_shares", 0) > 0:
        dv = depth.get("vwaps") or vwaps
        fillable = float(depth.get("fillable_shares") or 0)
        depth_levels = int(depth.get("depth_levels") or 1)
        fee_d = sum(float(v) * config.taker_fee_bps / 10_000.0 for v in dv)
        edge_at_size = 1.0 - sum(float(v) for v in dv) - fee_d

    edge_at_size_bps = edge_at_size * 10_000.0
    use_depth = config.use_depth_for_opportunity
    gate_edge = edge_at_size_bps if use_depth else edge_bps
    gate_fill = fillable if use_depth else size_cap
    opportunity = _opportunity_gate(gate_edge, gate_fill, liquidity_usd, config)
    slippage_bps = round(edge_at_size_bps - edge_bps, 2)
    profit_at_size = edge_at_size * min(config.depth_target_shares, fillable) if edge_at_size > 0 else 0.0

    return {
        "strategy_type": "multi_ask",
        "outcomes": outcomes,
        "outcome_vwaps": [round(v, 6) for v in (depth.get("vwaps") if depth else vwaps)],
        "outcome_sum": round(top_sum, 6),
        "raw_edge": round(raw_edge, 6),
        "edge": round(edge, 6),
        "edge_bps": round(edge_bps, 2),
        "size_cap": round(size_cap, 4),
        "liquidity_usd": round(liquidity_usd, 2),
        "fillable_shares": round(fillable, 4),
        "depth_levels": depth_levels,
        "edge_at_size": round(edge_at_size, 6),
        "edge_at_size_bps": round(edge_at_size_bps, 2),
        "slippage_bps": slippage_bps,
        "profit_at_size_usd": round(profit_at_size, 4),
        "opportunity": opportunity,
        "paper_tradable": False,
        "ladders": depth.get("ladders") if depth else None,
        **_profit_fields(edge, size_cap, top_sum),
    }
