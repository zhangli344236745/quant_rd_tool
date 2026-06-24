"""Background runner for crypto HFT market-making bots."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import logging
import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from quant_rd_tool.crypto_hft import cancel_bot_orders, default_exchange_factory, resolve_ccxt_symbol, run_cycle
from quant_rd_tool.crypto_hft_risk import begin_risk_session
from quant_rd_tool.crypto_hft_storage import (
    HftBotConfig,
    append_event,
    load_bot_config,
    load_bot_state,
    save_bot_state,
    validate_bot_id,
)

logger = logging.getLogger(__name__)


class ManagedHftBot:
    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.run_count = 0
        self.error_count = 0
        self.last_cycle_at: str | None = None
        self.last_error: str | None = None
        self.last_result: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        state = load_bot_state(self.bot_id)
        return {
            "bot_id": self.bot_id,
            "running": self.is_running(),
            "run_count": self.run_count,
            "error_count": self.error_count,
            "last_cycle_at": self.last_cycle_at,
            "last_error": self.last_error,
            "status": state.get("status", "stopped"),
            "last_result": self.last_result,
        }

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


class HftRunnerManager:
    def __init__(self) -> None:
        self._bots: dict[str, ManagedHftBot] = {}
        self._lock = threading.Lock()

    def register(self, cfg: HftBotConfig) -> dict[str, Any]:
        bid = validate_bot_id(cfg.bot_id)
        with self._lock:
            bot = self._bots.get(bid)
            if bot and bot.is_running():
                raise ValueError(f"bot '{bid}' is running; stop before update")
            from quant_rd_tool.crypto_hft_storage import save_bot_config

            save_bot_config(cfg)
            if bid not in self._bots:
                self._bots[bid] = ManagedHftBot(bid)
            return asdict(cfg)

    def start(self, bot_id: str, *, confirm_mainnet: bool = False) -> dict[str, Any]:
        bid = validate_bot_id(bot_id)
        cfg = load_bot_config(bid)
        if not cfg.testnet and not confirm_mainnet:
            raise ValueError("mainnet requires confirm_mainnet=true")
        with self._lock:
            bot = self._bots.setdefault(bid, ManagedHftBot(bid))
            if bot.is_running():
                return bot.public()
            state = load_bot_state(bid)
            begin_risk_session(state)
            state["status"] = "running"
            state["session_started_at"] = now_iso()
            state["last_error"] = None
            save_bot_state(bid, state)
            bot._stop.clear()
            thread = threading.Thread(target=self._loop, args=(bid,), daemon=True, name=f"hft-{bid}")
            bot._thread = thread
            thread.start()
            append_event(bid, {"type": "started", "testnet": cfg.testnet})
        return self.status_one(bid)

    def stop(self, bot_id: str, *, cancel_orders: bool = False) -> dict[str, Any]:
        bid = validate_bot_id(bot_id)
        with self._lock:
            bot = self._bots.get(bid)
            if bot:
                bot._stop.set()
        if bot and bot._thread:
            bot._thread.join(timeout=5)
        state = load_bot_state(bid)
        state["status"] = "stopped"
        save_bot_state(bid, state)
        if cancel_orders:
            try:
                cfg = load_bot_config(bid)
                ex = default_exchange_factory(cfg)
                sym = resolve_ccxt_symbol(cfg)
                open_orders = ex.fetch_open_orders(sym)
                cancel_bot_orders(ex, cfg, open_orders)
                append_event(bid, {"type": "stopped", "cancel_orders": len(open_orders)})
            except Exception as e:  # noqa: BLE001
                append_event(bid, {"type": "error", "action": "stop_cancel", "error": str(e)})
        else:
            append_event(bid, {"type": "stopped"})
        return self.status_one(bid)

    def remove(self, bot_id: str) -> dict[str, Any]:
        bid = validate_bot_id(bot_id)
        bot = self._bots.get(bid)
        if bot and bot.is_running():
            raise ValueError("stop bot before remove")
        from quant_rd_tool.crypto_hft_storage import delete_bot_config

        delete_bot_config(bid)
        with self._lock:
            self._bots.pop(bid, None)
        return {"removed": bid}

    def run_once(self, bot_id: str) -> dict[str, Any]:
        bid = validate_bot_id(bot_id)
        bot = self._bots.setdefault(bid, ManagedHftBot(bid))
        try:
            result = run_cycle(bid)
            bot.run_count += 1
            bot.last_cycle_at = now_iso()
            bot.last_result = {
                "mid": (result.get("book") or {}).get("mid"),
                "placed": result.get("placed"),
                "canceled": result.get("canceled"),
            }
            bot.last_error = None
            return result
        except Exception as e:  # noqa: BLE001
            bot.error_count += 1
            bot.last_error = str(e)
            state = load_bot_state(bid)
            state["status"] = "error"
            state["last_error"] = str(e)
            save_bot_state(bid, state)
            append_event(bid, {"type": "error", "action": "cycle", "error": str(e)})
            raise

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            bots = list(self._bots.values())
        if not bots:
            from quant_rd_tool.crypto_hft_storage import list_bot_ids

            return [ManagedHftBot(bid).public() for bid in list_bot_ids()]
        return [b.public() for b in bots]

    def status_one(self, bot_id: str) -> dict[str, Any]:
        bid = validate_bot_id(bot_id)
        bot = self._bots.get(bid) or ManagedHftBot(bid)
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

    def _loop(self, bot_id: str) -> None:
        bot = self._bots.get(bot_id)
        if bot is None:
            return
        while not bot._stop.is_set():
            started = time.time()
            try:
                self.run_once(bot_id)
            except Exception:
                logger.exception("HFT bot %s cycle failed", bot_id)
            try:
                cfg = load_bot_config(bot_id)
                wait_ms = max(int(cfg.interval_ms), 1000)
            except Exception:
                wait_ms = 1500
            elapsed = time.time() - started
            sleep_s = max(wait_ms / 1000.0 - elapsed, 0.2)
            if bot._stop.wait(timeout=sleep_s):
                break
        state = load_bot_state(bot_id)
        if state.get("status") == "running":
            state["status"] = "stopped"
            save_bot_state(bot_id, state)


_MANAGER: HftRunnerManager | None = None


def get_hft_manager() -> HftRunnerManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = HftRunnerManager()
    return _MANAGER
