"""REST-polling market-making engine for Binance spot + USDT-M perp."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.config import settings
from quant_rd_tool.crypto_hft_storage import (
    HftBotConfig,
    append_event,
    load_bot_config,
    load_bot_state,
    load_global_config,
    save_bot_state,
)
from quant_rd_tool.crypto_hft_execution import (
    build_limit_order_params,
    bump_execution_stats,
    cancel_orders_batch,
    plan_reconcile_tagged,
    prepare_quotes,
)
from quant_rd_tool.crypto_hft_risk import (
    RiskLimits,
    filter_quotes_by_risk,
    refresh_risk_state,
    resolve_max_inventory_usdt,
)
from quant_rd_tool.crypto_hft_strategies import Quote, build_quotes
from quant_rd_tool.crypto_ops_control import is_kill_switch_active

logger = logging.getLogger(__name__)

ExchangeFactory = Callable[[HftBotConfig], Any]


@dataclass
class ReconcilePlan:
    cancel: list[dict[str, Any]]
    place: list[Quote]


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def resolve_ccxt_symbol(cfg: HftBotConfig) -> str:
    base = cfg.symbol.strip().upper()
    q = cfg.quote.strip().upper()
    if cfg.market_type == "future":
        return f"{base}/{q}:{q}"
    return cxt.to_ccxt_symbol(base, q)


def default_exchange_factory(cfg: HftBotConfig) -> Any:
    if not (settings.binance_api_key and settings.binance_api_secret):
        raise ValueError("需配置 BINANCE_API_KEY / BINANCE_API_SECRET")
    testnet = cfg.testnet or settings.binance_testnet
    ex = cxt.create_exchange(
        "binance",
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        testnet=testnet,
        api_base=settings.binance_api_base,
        http_proxy=settings.http_proxy,
        https_proxy=settings.https_proxy,
        market_type=cfg.market_type,
    )
    try:
        if getattr(ex, "load_time_difference", None):
            ex.load_time_difference()
    except Exception:
        pass
    return ex


def summarize_book(book: dict[str, Any]) -> dict[str, Any]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return {"best_bid": None, "best_ask": None, "mid": None, "spread_bps": None}
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 10_000 if mid > 0 else None
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_bps": spread_bps,
        "bids": bids[:5],
        "asks": asks[:5],
    }


def fetch_inventory(ex, cfg: HftBotConfig, state: dict[str, Any]) -> dict[str, float]:
    symbol = resolve_ccxt_symbol(cfg)
    base = cfg.symbol.strip().upper()
    if cfg.market_type == "future":
        positions = ex.fetch_positions([symbol])
        pos = 0.0
        entry = 0.0
        upnl = 0.0
        for p in positions:
            if p.get("symbol") == symbol:
                amt = float(p.get("contracts") or 0)
                if amt:
                    pos = amt if str(p.get("side", "")).lower() != "short" else -amt
                entry = float(p.get("entryPrice") or p.get("entry_price") or 0)
                raw_upnl = p.get("unrealizedPnl")
                if raw_upnl not in (None, ""):
                    upnl = float(raw_upnl)
                break
        ticker = ex.fetch_ticker(symbol)
        mark = float(ticker.get("last") or ticker.get("close") or 0)
        inv_usdt = pos * mark
        return {
            "inventory_base": pos,
            "inventory_usdt": inv_usdt,
            "mark_price": mark,
            "avg_entry_price": entry,
            "unrealized_pnl": upnl,
        }
    bal = ex.fetch_balance()
    free = float((bal.get("free") or {}).get(base) or 0)
    ticker = ex.fetch_ticker(symbol)
    mark = float(ticker.get("last") or ticker.get("close") or 0)
    return {
        "inventory_base": free,
        "inventory_usdt": free * mark,
        "mark_price": mark,
        "avg_entry_price": float(state.get("avg_entry_price") or 0),
        "unrealized_pnl": None,
    }


def fetch_recent_fills(ex, symbol: str, *, since_ms: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if since_ms > 0:
        params["since"] = since_ms
    try:
        return list(ex.fetch_my_trades(symbol, None, None, params) or [])
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_my_trades failed: %s", e)
        return []


def build_risk_limits(cfg: HftBotConfig) -> RiskLimits:
    global_cfg = load_global_config()
    return RiskLimits(
        max_session_loss_usdt=float(cfg.max_session_loss_usdt or 0),
        max_inventory_usdt=resolve_max_inventory_usdt(
            bot_max_inventory_usdt=float(cfg.max_inventory_usdt or 0),
            strategy_params=cfg.strategy_params,
        ),
        max_daily_loss_usdt=float(global_cfg.max_daily_loss_usdt or 0),
    )


def price_within_tolerance(existing: float, target: float, tolerance_bps: float) -> bool:
    if existing <= 0 or target <= 0:
        return False
    diff_bps = abs(existing - target) / target * 10_000
    return diff_bps <= tolerance_bps


def plan_reconcile(
    open_orders: list[dict[str, Any]],
    desired: list[Quote],
    *,
    tolerance_bps: float,
) -> ReconcilePlan:
    unmatched_open = list(open_orders)
    to_place: list[Quote] = []
    to_cancel: list[dict[str, Any]] = []

    for quote in desired:
        match = None
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


def place_limit_quote(ex, cfg: HftBotConfig, quote: Quote) -> dict[str, Any]:
    symbol = resolve_ccxt_symbol(cfg)
    notional = quote.price * quote.amount
    if notional > cfg.max_order_size_usdt * 1.05:
        raise ValueError(f"order notional {notional:.2f} exceeds max_order_size_usdt")
    params = build_limit_order_params(cfg, quote)
    order = ex.create_order(symbol, "limit", quote.side, quote.amount, quote.price, params)
    return order


def cancel_bot_orders(ex, cfg: HftBotConfig, orders: list[dict[str, Any]]) -> int:
    symbol = resolve_ccxt_symbol(cfg)
    n = 0
    for o in orders:
        oid = o.get("id")
        if not oid:
            continue
        try:
            ex.cancel_order(str(oid), symbol)
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("cancel failed %s: %s", oid, e)
    return n


def run_cycle(
    bot_id: str,
    *,
    exchange_factory: ExchangeFactory | None = None,
) -> dict[str, Any]:
    if is_kill_switch_active():
        append_event(bot_id, {"type": "skipped", "reason": "kill_switch"})
        return {"bot_id": bot_id, "skipped": "kill_switch"}

    cfg = load_bot_config(bot_id)
    state = load_bot_state(bot_id)
    factory = exchange_factory or default_exchange_factory
    ex = factory(cfg)
    symbol = resolve_ccxt_symbol(cfg)

    book = ex.fetch_order_book(symbol, limit=cfg.book_depth)
    summary = summarize_book(book)
    mid = summary.get("mid")
    if not mid:
        raise ValueError("empty order book")

    inv = fetch_inventory(ex, cfg, state)
    inventory_usdt = float(inv.get("inventory_usdt") or 0)

    since_ms = int(state.get("last_fill_ts_ms") or 0)
    if since_ms <= 0 and state.get("session_started_at"):
        since_ms = int(datetime.now(UTC).timestamp() * 1000) - 86_400_000
    risk_decision, new_fills = refresh_risk_state(
        state,
        inventory=inv,
        mid=mid,
        limits=build_risk_limits(cfg),
        fills=fetch_recent_fills(ex, symbol, since_ms=since_ms),
        maker_fee_bps=cfg.maker_fee_bps,
    )
    for fill in new_fills:
        append_event(
            bot_id,
            {
                "type": "fill",
                "side": fill.get("side"),
                "price": fill.get("price"),
                "amount": fill.get("amount"),
                "trade_id": fill.get("id"),
            },
        )
    if risk_decision.halted and not state.get("_risk_event_logged"):
        append_event(bot_id, {"type": "risk_halt", "reason": risk_decision.reason})
        state["_risk_event_logged"] = True

    center = float(state.get("last_mid") or mid)
    if cfg.strategy_id == "grid_mm":
        reanchor_bps = float((cfg.strategy_params or {}).get("reanchor_bps", 200))
        drift_bps = abs(mid - center) / mid * 10_000 if mid > 0 else 0
        if drift_bps > reanchor_bps:
            center = mid

    desired = build_quotes(
        cfg.strategy_id,
        book,
        inventory_usdt=inventory_usdt,
        params=cfg.strategy_params,
        center_price=center,
        state=state,
    )
    desired, prep_stats = prepare_quotes(
        desired,
        book,
        maker_fee_bps=cfg.maker_fee_bps,
        min_edge_bps=cfg.min_edge_bps,
    )
    desired = filter_quotes_by_risk(desired, risk_decision)
    open_orders = ex.fetch_open_orders(symbol)
    if len(open_orders) > cfg.max_open_orders:
        open_orders = open_orders[: cfg.max_open_orders]

    plan = plan_reconcile_tagged(
        open_orders,
        desired,
        tolerance_bps=cfg.price_tolerance_bps,
        bot_id=cfg.bot_id,
        use_tags=cfg.use_client_order_tags,
    )
    canceled = 0
    placed = 0
    if plan.cancel:
        canceled = cancel_orders_batch(ex, symbol, plan.cancel, batch=cfg.batch_cancel)
        if cfg.batch_cancel and canceled:
            bump_execution_stats(state, batch_cancel_used=1)
        for o in plan.cancel:
            append_event(bot_id, {"type": "order_canceled", "order_id": o.get("id"), "side": o.get("side")})

    for q in plan.place:
        try:
            order = place_limit_quote(ex, cfg, q)
            placed += 1
            append_event(
                bot_id,
                {
                    "type": "order_placed",
                    "side": q.side,
                    "price": q.price,
                    "amount": q.amount,
                    "order_id": order.get("id"),
                    "tag": q.tag,
                },
            )
        except Exception as e:  # noqa: BLE001
            append_event(bot_id, {"type": "error", "action": "place", "error": str(e), "tag": q.tag})

    open_after = ex.fetch_open_orders(symbol)
    bump_execution_stats(
        state,
        placed=placed,
        canceled=canceled,
        rejected_cross=prep_stats.rejected_cross,
        fee_adjusted=prep_stats.fee_adjusted,
    )
    state.update(
        {
            "status": "risk_halted" if risk_decision.halted else "running",
            "inventory_base": inv.get("inventory_base", 0),
            "inventory_usdt": inventory_usdt,
            "last_mid": mid,
            "last_cycle_at": _iso_now(),
            "last_error": None,
            "open_order_ids": [str(o.get("id")) for o in open_after if o.get("id")],
        }
    )
    if not risk_decision.halted:
        state.pop("_risk_event_logged", None)
    save_bot_state(bot_id, state)
    append_event(
        bot_id,
        {
            "type": "cycle",
            "mid": mid,
            "spread_bps": summary.get("spread_bps"),
            "desired_quotes": len(desired),
            "placed": placed,
            "canceled": canceled,
            "rejected_cross": prep_stats.rejected_cross,
            "fee_adjusted": prep_stats.fee_adjusted,
            "session_pnl_usdt": (state.get("pnl") or {}).get("session_usdt"),
            "risk_halted": risk_decision.halted,
        },
    )
    return {
        "bot_id": bot_id,
        "book": summary,
        "inventory": inv,
        "desired_quotes": [q.__dict__ for q in desired],
        "open_orders": open_after,
        "placed": placed,
        "canceled": canceled,
        "risk": state.get("risk"),
        "pnl": state.get("pnl"),
    }


def fetch_book_snapshot(
    *,
    symbol: str,
    market_type: str = "future",
    quote: str = "USDT",
    testnet: bool = True,
    book_depth: int = 5,
    exchange_factory: ExchangeFactory | None = None,
) -> dict[str, Any]:
    cfg = HftBotConfig(
        bot_id="snapshot",
        symbol=symbol,
        quote=quote,
        market_type=market_type,  # type: ignore[arg-type]
        testnet=testnet,
        book_depth=book_depth,
    )
    factory = exchange_factory or default_exchange_factory
    ex = factory(cfg)
    sym = resolve_ccxt_symbol(cfg)
    book = ex.fetch_order_book(sym, limit=book_depth)
    return {"symbol": sym, "book": summarize_book(book)}
