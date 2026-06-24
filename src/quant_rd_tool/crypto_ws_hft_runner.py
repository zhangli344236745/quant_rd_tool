"""Asyncio runner for WebSocket crypto market-making bots."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from quant_rd_tool.crypto_hft_common import resolve_ccxt_symbol
from quant_rd_tool.crypto_hft_execution import bump_execution_stats
from quant_rd_tool.crypto_hft_risk import begin_risk_session
from quant_rd_tool.crypto_ws_hft import (
    cancel_orders_async,
    default_pro_exchange_factory,
    handle_book_update,
)
from quant_rd_tool.crypto_ws_hft_storage import (
    WsHftBotConfig,
    append_event,
    load_bot_config,
    load_bot_state,
    save_bot_config,
    save_bot_state,
    validate_bot_id,
)

logger = logging.getLogger(__name__)


class ManagedWsHftBot:
    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.live_trading = False
        self.reconcile_count = 0
        self.error_count = 0
        self.last_reconcile_at: str | None = None
        self.last_error: str | None = None
        self.last_result: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        state = load_bot_state(self.bot_id)
        return {
            "bot_id": self.bot_id,
            "running": self.is_running(),
            "live_trading": self.live_trading,
            "reconcile_count": self.reconcile_count,
            "error_count": self.error_count,
            "last_reconcile_at": self.last_reconcile_at,
            "last_error": self.last_error,
            "status": state.get("status", "stopped"),
            "last_result": self.last_result,
        }

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()


class WsHftRunnerManager:
    def __init__(self) -> None:
        self._bots: dict[str, ManagedWsHftBot] = {}
        self._lock = asyncio.Lock()

    async def register(self, cfg: WsHftBotConfig) -> dict[str, Any]:
        bid = validate_bot_id(cfg.bot_id)
        async with self._lock:
            bot = self._bots.get(bid)
            if bot and bot.is_running():
                raise ValueError(f"bot '{bid}' is running; stop before update")
            save_bot_config(cfg)
            if bid not in self._bots:
                self._bots[bid] = ManagedWsHftBot(bid)
            return asdict(cfg)

    async def start(
        self,
        bot_id: str,
        *,
        confirm_live: bool = False,
        confirm_mainnet: bool = False,
    ) -> dict[str, Any]:
        bid = validate_bot_id(bot_id)
        cfg = load_bot_config(bid)
        if not cfg.testnet and not confirm_mainnet:
            raise ValueError("mainnet requires confirm_mainnet=true")
        if not cfg.dry_run and not confirm_live:
            raise ValueError("live trading requires confirm_live=true")

        async with self._lock:
            bot = self._bots.setdefault(bid, ManagedWsHftBot(bid))
            if bot.is_running():
                return await self.status_one(bid)
            bot.live_trading = not cfg.dry_run and confirm_live
            bot._stop.clear()
            state = load_bot_state(bid)
            begin_risk_session(state)
            state["status"] = "running"
            state["session_started_at"] = now_iso()
            state["last_error"] = None
            save_bot_state(bid, state)
            bot._task = asyncio.create_task(self._run_loop(bid), name=f"ws-hft-{bid}")
            append_event(
                bid,
                {
                    "type": "started",
                    "testnet": cfg.testnet,
                    "dry_run": cfg.dry_run or not bot.live_trading,
                    "trigger_mode": cfg.trigger_mode,
                },
            )
        return await self.status_one(bid)

    async def stop(self, bot_id: str, *, cancel_orders: bool = False) -> dict[str, Any]:
        bid = validate_bot_id(bot_id)
        bot = self._bots.get(bid)
        if bot:
            bot._stop.set()
            if bot._task:
                try:
                    await asyncio.wait_for(bot._task, timeout=8)
                except TimeoutError:
                    bot._task.cancel()
                    try:
                        await bot._task
                    except asyncio.CancelledError:
                        pass
        state = load_bot_state(bid)
        state["status"] = "stopped"
        save_bot_state(bid, state)
        if cancel_orders and bot:
            try:
                cfg = load_bot_config(bid)
                ex = await default_pro_exchange_factory(cfg)
                sym = resolve_ccxt_symbol(
                    symbol=cfg.symbol, quote=cfg.quote, market_type=cfg.market_type
                )
                open_orders = await ex.fetch_open_orders(sym)
                await cancel_orders_async(ex, cfg, open_orders)
                await ex.close()
                append_event(bid, {"type": "stopped", "cancel_orders": len(open_orders)})
            except Exception as e:  # noqa: BLE001
                append_event(bid, {"type": "error", "action": "stop_cancel", "error": str(e)})
        else:
            append_event(bid, {"type": "stopped"})
        return await self.status_one(bid)

    async def remove(self, bot_id: str) -> dict[str, Any]:
        bid = validate_bot_id(bot_id)
        bot = self._bots.get(bid)
        if bot and bot.is_running():
            raise ValueError("stop bot before remove")
        from quant_rd_tool.crypto_ws_hft_storage import delete_bot_config

        delete_bot_config(bid)
        async with self._lock:
            self._bots.pop(bid, None)
        return {"removed": bid}

    async def status(self) -> list[dict[str, Any]]:
        async with self._lock:
            bots = list(self._bots.values())
        if not bots:
            from quant_rd_tool.crypto_ws_hft_storage import list_bot_ids

            return [ManagedWsHftBot(bid).public() for bid in list_bot_ids()]
        return [b.public() for b in bots]

    async def status_one(self, bot_id: str) -> dict[str, Any]:
        bid = validate_bot_id(bot_id)
        bot = self._bots.get(bid) or ManagedWsHftBot(bid)
        pub = bot.public()
        try:
            cfg = load_bot_config(bid)
            pub["config"] = asdict(cfg)
            pub["registered"] = True
        except ValueError:
            pub["config"] = None
            pub["registered"] = False
        pub["state"] = load_bot_state(bid)
        return pub

    async def _run_loop(self, bot_id: str) -> None:
        bot = self._bots.get(bot_id)
        if bot is None:
            return
        ex = None
        try:
            while not bot._stop.is_set():
                try:
                    cfg = load_bot_config(bot_id)
                    if ex is None:
                        ex = await default_pro_exchange_factory(cfg)
                    symbol = resolve_ccxt_symbol(
                        symbol=cfg.symbol, quote=cfg.quote, market_type=cfg.market_type
                    )
                    book = await ex.watch_order_book(symbol, limit=cfg.book_depth)
                    recv_ns = __import__("time").monotonic_ns()
                    result = await handle_book_update(
                        bot_id,
                        book,
                        book_recv_ns=recv_ns,
                        live_trading=bot.live_trading,
                        exchange=ex,
                    )
                    bot.reconcile_count += 1
                    bot.last_reconcile_at = now_iso()
                    if result.get("skipped") != "throttled":
                        bot.last_result = {
                            "mid": (result.get("book") or {}).get("mid"),
                            "placed": result.get("placed"),
                            "canceled": result.get("canceled"),
                            "latency_us": result.get("latency_us"),
                            "dry_run": result.get("dry_run"),
                        }
                    bot.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    err = str(e).lower()
                    transient = any(
                        k in err
                        for k in ("connection", "timeout", "disconnect", "closed", "network", "reset")
                    )
                    if transient and not bot._stop.is_set():
                        state = load_bot_state(bot_id)
                        bump_execution_stats(state, reconnects=1)
                        save_bot_state(bot_id, state)
                        append_event(bot_id, {"type": "ws_reconnect", "error": str(e)})
                        if ex is not None:
                            try:
                                await ex.close()
                            except Exception:
                                pass
                        ex = None
                        await asyncio.sleep(1.0)
                        continue
                    bot.error_count += 1
                    bot.last_error = str(e)
                    state = load_bot_state(bot_id)
                    state["status"] = "error"
                    state["last_error"] = str(e)
                    save_bot_state(bot_id, state)
                    append_event(bot_id, {"type": "error", "action": "reconcile", "error": str(e)})
                    logger.exception("WS HFT bot %s reconcile failed", bot_id)
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            bot.error_count += 1
            bot.last_error = str(e)
            state = load_bot_state(bot_id)
            state["status"] = "error"
            state["last_error"] = str(e)
            save_bot_state(bot_id, state)
            append_event(bot_id, {"type": "error", "action": "ws_loop", "error": str(e)})
            logger.exception("WS HFT bot %s loop failed", bot_id)
        finally:
            if ex is not None:
                try:
                    await ex.close()
                except Exception:
                    pass
            state = load_bot_state(bot_id)
            if state.get("status") == "running":
                state["status"] = "stopped"
                save_bot_state(bot_id, state)


_MANAGER: WsHftRunnerManager | None = None


def get_ws_hft_manager() -> WsHftRunnerManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = WsHftRunnerManager()
    return _MANAGER
