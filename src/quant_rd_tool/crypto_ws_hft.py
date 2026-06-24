"""WebSocket event-driven market-making engine via ccxt.pro."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from quant_rd_tool.config import settings
from quant_rd_tool.crypto_hft_common import plan_reconcile, resolve_ccxt_symbol, summarize_book
from quant_rd_tool.crypto_hft_execution import (
    ExecutionPrepStats,
    build_limit_order_params,
    bump_execution_stats,
    cancel_orders_batch_async,
    plan_reconcile_tagged,
    prepare_quotes,
)
from quant_rd_tool.crypto_hft_risk import (
    RiskLimits,
    begin_risk_session,
    filter_quotes_by_risk,
    refresh_risk_state,
    resolve_max_inventory_usdt,
)
from quant_rd_tool.crypto_ops_control import is_kill_switch_active
from quant_rd_tool.crypto_hft_strategies import Quote, build_quotes
from quant_rd_tool.crypto_ws_hft_storage import (
    WsHftBotConfig,
    append_event,
    load_bot_config,
    load_bot_state,
    load_global_config,
    save_bot_state,
)

logger = logging.getLogger(__name__)

ProExchangeFactory = Callable[[WsHftBotConfig], Awaitable[Any]]
FetchInventoryFn = Callable[[Any, WsHftBotConfig, dict[str, Any]], Awaitable[dict[str, float]]]
FetchOpenOrdersFn = Callable[[Any, WsHftBotConfig], Awaitable[list[dict[str, Any]]]]

_LATENCY_SAMPLE_CAP = 100


def _iso_now() -> str:
    return now_iso()


def should_process_update(
    cfg: WsHftBotConfig,
    *,
    last_process_ns: int | None,
    now_ns: int,
) -> bool:
    if cfg.trigger_mode == "every_update":
        return True
    if last_process_ns is None:
        return True
    throttle_ns = max(int(cfg.throttle_ms), 1) * 1_000_000
    return (now_ns - last_process_ns) >= throttle_ns


def update_latency_stats(state: dict[str, Any], latency_us: int) -> dict[str, Any]:
    lat = dict(state.get("latency_us") or {})
    samples: list[int] = list(lat.get("samples") or [])
    samples.append(int(latency_us))
    if len(samples) > _LATENCY_SAMPLE_CAP:
        samples = samples[-_LATENCY_SAMPLE_CAP:]
    sorted_samples = sorted(samples)
    n = len(sorted_samples)
    if n:
        if n % 2 == 1:
            p50 = sorted_samples[n // 2]
        else:
            p50 = (sorted_samples[n // 2 - 1] + sorted_samples[n // 2]) // 2
        p95_idx = min(int(n * 0.95), n - 1)
        p95 = sorted_samples[p95_idx]
    else:
        p50 = None
        p95 = None
    lat.update({"last": latency_us, "p50": p50, "p95": p95, "samples": samples})
    state["latency_us"] = lat
    return state


@dataclass
class BookCyclePlan:
    summary: dict[str, Any]
    desired: list[Quote]
    plan: Any
    center_price: float
    inventory: dict[str, float]
    prep_stats: ExecutionPrepStats


def build_cycle_plan(
    cfg: WsHftBotConfig,
    book: dict[str, Any],
    state: dict[str, Any],
    open_orders: list[dict[str, Any]],
    inventory: dict[str, float],
) -> BookCyclePlan:
    summary = summarize_book(book)
    mid = summary.get("mid")
    if not mid:
        raise ValueError("empty order book")

    inventory_usdt = float(inventory.get("inventory_usdt") or 0)
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
    trimmed = open_orders[: cfg.max_open_orders]
    plan = plan_reconcile_tagged(
        trimmed,
        desired,
        tolerance_bps=cfg.price_tolerance_bps,
        bot_id=cfg.bot_id,
        use_tags=cfg.use_client_order_tags,
    )
    return BookCyclePlan(
        summary=summary,
        desired=desired,
        plan=plan,
        center_price=center,
        inventory=inventory,
        prep_stats=prep_stats,
    )


async def default_pro_exchange_factory(cfg: WsHftBotConfig) -> Any:
    if not (settings.binance_api_key and settings.binance_api_secret):
        raise ValueError("需配置 BINANCE_API_KEY / BINANCE_API_SECRET")
    import ccxt.pro as ccxtpro

    testnet = cfg.testnet or settings.binance_testnet
    opts: dict[str, Any] = {
        "enableRateLimit": True,
        "apiKey": settings.binance_api_key,
        "secret": settings.binance_api_secret,
        "options": {
            "defaultType": cfg.market_type,
            "adjustForTimeDifference": True,
            "recvWindow": 5000,
        },
    }
    if testnet:
        opts["options"]["sandboxMode"] = True
    ex = ccxtpro.binance(opts)
    if settings.http_proxy or settings.https_proxy:
        ex.proxies = {}
        if settings.http_proxy:
            ex.proxies["http"] = settings.http_proxy
        if settings.https_proxy:
            ex.proxies["https"] = settings.https_proxy
    if settings.binance_api_base:
        try:
            ex.urls["api"] = {"public": settings.binance_api_base, "private": settings.binance_api_base}
        except Exception:
            pass
    try:
        if getattr(ex, "load_time_difference", None):
            await ex.load_time_difference()
    except Exception:
        pass
    return ex


async def fetch_inventory_async(ex: Any, cfg: WsHftBotConfig, state: dict[str, Any]) -> dict[str, float]:
    symbol = resolve_ccxt_symbol(
        symbol=cfg.symbol, quote=cfg.quote, market_type=cfg.market_type
    )
    base = cfg.symbol.strip().upper()
    if cfg.market_type == "future":
        positions = await ex.fetch_positions([symbol])
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
        ticker = await ex.fetch_ticker(symbol)
        mark = float(ticker.get("last") or ticker.get("close") or 0)
        inv_usdt = pos * mark
        return {
            "inventory_base": pos,
            "inventory_usdt": inv_usdt,
            "mark_price": mark,
            "avg_entry_price": entry,
            "unrealized_pnl": upnl,
        }
    bal = await ex.fetch_balance()
    free = float((bal.get("free") or {}).get(base) or 0)
    ticker = await ex.fetch_ticker(symbol)
    mark = float(ticker.get("last") or ticker.get("close") or 0)
    return {
        "inventory_base": free,
        "inventory_usdt": free * mark,
        "mark_price": mark,
        "avg_entry_price": float(state.get("avg_entry_price") or 0),
        "unrealized_pnl": None,
    }


async def fetch_recent_fills_async(ex: Any, symbol: str, *, since_ms: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if since_ms > 0:
        params["since"] = since_ms
    try:
        return list(await ex.fetch_my_trades(symbol, None, None, params) or [])
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_my_trades failed: %s", e)
        return []


def build_ws_risk_limits(cfg: WsHftBotConfig) -> RiskLimits:
    global_cfg = load_global_config()
    return RiskLimits(
        max_session_loss_usdt=float(cfg.max_session_loss_usdt or 0),
        max_inventory_usdt=resolve_max_inventory_usdt(
            bot_max_inventory_usdt=float(cfg.max_inventory_usdt or 0),
            strategy_params=cfg.strategy_params,
        ),
        max_daily_loss_usdt=float(global_cfg.max_daily_loss_usdt or 0),
    )


async def fetch_open_orders_async(ex: Any, cfg: WsHftBotConfig) -> list[dict[str, Any]]:
    symbol = resolve_ccxt_symbol(
        symbol=cfg.symbol, quote=cfg.quote, market_type=cfg.market_type
    )
    return await ex.fetch_open_orders(symbol)


async def place_limit_quote_async(ex: Any, cfg: WsHftBotConfig, quote: Quote) -> dict[str, Any]:
    symbol = resolve_ccxt_symbol(
        symbol=cfg.symbol, quote=cfg.quote, market_type=cfg.market_type
    )
    notional = quote.price * quote.amount
    if notional > cfg.max_order_size_usdt * 1.05:
        raise ValueError(f"order notional {notional:.2f} exceeds max_order_size_usdt")
    params = build_limit_order_params(cfg, quote)
    return await ex.create_order(symbol, "limit", quote.side, quote.amount, quote.price, params)


async def cancel_orders_async(ex: Any, cfg: WsHftBotConfig, orders: list[dict[str, Any]]) -> int:
    symbol = resolve_ccxt_symbol(
        symbol=cfg.symbol, quote=cfg.quote, market_type=cfg.market_type
    )
    return await cancel_orders_batch_async(ex, symbol, orders, batch=cfg.batch_cancel)


async def handle_book_update(
    bot_id: str,
    book: dict[str, Any],
    *,
    book_recv_ns: int | None = None,
    live_trading: bool = False,
    exchange: Any | None = None,
    exchange_factory: ProExchangeFactory | None = None,
    fetch_inventory: FetchInventoryFn | None = None,
    fetch_open_orders: FetchOpenOrdersFn | None = None,
) -> dict[str, Any]:
    if is_kill_switch_active():
        append_event(bot_id, {"type": "skipped", "reason": "kill_switch"})
        return {"bot_id": bot_id, "skipped": "kill_switch"}

    recv_ns = book_recv_ns if book_recv_ns is not None else time.monotonic_ns()
    cfg = load_bot_config(bot_id)
    state = load_bot_state(bot_id)
    state["book_updates_total"] = int(state.get("book_updates_total") or 0) + 1

    last_process_ns = state.get("last_process_ns")
    now_ns = recv_ns
    if not should_process_update(cfg, last_process_ns=last_process_ns, now_ns=now_ns):
        state["throttled_skips"] = int(state.get("throttled_skips") or 0) + 1
        save_bot_state(bot_id, state)
        return {"bot_id": bot_id, "skipped": "throttled"}

    owns_exchange = exchange is None
    ex = exchange
    if ex is None:
        factory = exchange_factory or default_pro_exchange_factory
        ex = await factory(cfg)

    inv_fn = fetch_inventory or fetch_inventory_async
    orders_fn = fetch_open_orders or fetch_open_orders_async

    try:
        open_orders = await orders_fn(ex, cfg)
        inventory = await inv_fn(ex, cfg, state)
        symbol = resolve_ccxt_symbol_for_cfg(cfg)
        summary_preview = summarize_book(book)
        mid_preview = summary_preview.get("mid")
        since_ms = int(state.get("last_fill_ts_ms") or 0)
        if since_ms <= 0 and state.get("session_started_at"):
            since_ms = int(datetime.now(UTC).timestamp() * 1000) - 86_400_000
        fills = await fetch_recent_fills_async(ex, symbol, since_ms=since_ms)
        risk_decision, new_fills = refresh_risk_state(
            state,
            inventory=inventory,
            mid=mid_preview,
            limits=build_ws_risk_limits(cfg),
            fills=fills,
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

        cycle = build_cycle_plan(cfg, book, state, open_orders, inventory)
        if risk_decision.halted:
            cycle.plan.place = []
            cycle.plan.cancel = list(open_orders)
        else:
            filtered = filter_quotes_by_risk(cycle.desired, risk_decision)
            if len(filtered) != len(cycle.desired):
                trimmed = open_orders[: cfg.max_open_orders]
                cycle.plan = plan_reconcile_tagged(
                    trimmed,
                    filtered,
                    tolerance_bps=cfg.price_tolerance_bps,
                    bot_id=cfg.bot_id,
                    use_tags=cfg.use_client_order_tags,
                )
                cycle.desired = filtered

        placed = 0
        canceled = 0
        dry_run = cfg.dry_run or not live_trading

        if dry_run:
            append_event(
                bot_id,
                {
                    "type": "dry_run_plan",
                    "would_cancel": len(cycle.plan.cancel),
                    "would_place": len(cycle.plan.place),
                    "mid": cycle.summary.get("mid"),
                },
            )
        else:
            canceled = await cancel_orders_async(ex, cfg, cycle.plan.cancel)
            if cfg.batch_cancel and canceled:
                bump_execution_stats(state, batch_cancel_used=1)
            for o in cycle.plan.cancel:
                append_event(
                    bot_id,
                    {"type": "order_canceled", "order_id": o.get("id"), "side": o.get("side")},
                )
            for q in cycle.plan.place:
                try:
                    order = await place_limit_quote_async(ex, cfg, q)
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
                    append_event(
                        bot_id,
                        {"type": "error", "action": "place", "error": str(e), "tag": q.tag},
                    )

        done_ns = time.monotonic_ns()
        latency_us = (done_ns - recv_ns) // 1000
        state = update_latency_stats(state, latency_us)
        bump_execution_stats(
            state,
            placed=placed,
            canceled=canceled,
            rejected_cross=cycle.prep_stats.rejected_cross,
            fee_adjusted=cycle.prep_stats.fee_adjusted,
        )
        state.update(
            {
                "status": "risk_halted" if risk_decision.halted else "running",
                "inventory_base": inventory.get("inventory_base", 0),
                "inventory_usdt": float(inventory.get("inventory_usdt") or 0),
                "last_mid": cycle.summary.get("mid"),
                "last_reconcile_at": _iso_now(),
                "last_error": None,
                "last_process_ns": now_ns,
                "reconciles_total": int(state.get("reconciles_total") or 0) + 1,
            }
        )
        if not risk_decision.halted:
            state.pop("_risk_event_logged", None)
        if not dry_run:
            open_after = await orders_fn(ex, cfg)
            state["open_order_ids"] = [str(o.get("id")) for o in open_after if o.get("id")]

        save_bot_state(bot_id, state)
        append_event(
            bot_id,
            {
                "type": "reconcile",
                "mid": cycle.summary.get("mid"),
                "spread_bps": cycle.summary.get("spread_bps"),
                "desired_quotes": len(cycle.desired),
                "placed": placed,
                "canceled": canceled,
                "dry_run": dry_run,
                "latency_us": latency_us,
                "rejected_cross": cycle.prep_stats.rejected_cross,
                "fee_adjusted": cycle.prep_stats.fee_adjusted,
                "session_pnl_usdt": (state.get("pnl") or {}).get("session_usdt"),
                "risk_halted": risk_decision.halted,
            },
        )
        return {
            "bot_id": bot_id,
            "book": cycle.summary,
            "inventory": inventory,
            "desired_quotes": [q.__dict__ for q in cycle.desired],
            "placed": placed,
            "canceled": canceled,
            "dry_run": dry_run,
            "latency_us": latency_us,
            "risk": state.get("risk"),
            "pnl": state.get("pnl"),
        }
    finally:
        if owns_exchange and ex is not None:
            try:
                await ex.close()
            except Exception:
                pass


def resolve_ccxt_symbol_for_cfg(cfg: WsHftBotConfig) -> str:
    return resolve_ccxt_symbol(
        symbol=cfg.symbol, quote=cfg.quote, market_type=cfg.market_type
    )
