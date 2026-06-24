"""In-process scheduler that hosts crypto bots and runs them on an interval.

Bots previously only ran when a human clicked "run". This registers a bot once
and a background thread calls ``run_once`` every ``interval_minutes`` (per-bar
dedup inside the bot prevents double-acting). Start/stop/status are exposed so
the UI can manage live/paper bots. Designed to be unit-testable: registration
and a single managed cycle are decoupled from the threading loop.
"""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

BotKind = Literal["spot", "perp"]
BotStatus = Literal["running", "stopped", "error"]


@dataclass
class ManagedBot:
    bot_id: str
    kind: BotKind
    config: dict[str, Any]
    interval_minutes: int = 60
    status: BotStatus = "stopped"
    run_count: int = 0
    error_count: int = 0
    last_run_at: str | None = None
    last_result: dict[str, Any] | None = None
    last_error: str | None = None
    created_at: str = field(default_factory=lambda: now_iso())
    _thread: threading.Thread | None = field(default=None, repr=False, compare=False)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def public(self) -> dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "kind": self.kind,
            "config": self.config,
            "interval_minutes": self.interval_minutes,
            "status": self.status,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "last_result": self.last_result,
        }


# Builds (bot_id, kind, config) -> object exposing run_once() -> dict.
BotFactory = Callable[[str, dict[str, Any]], Any]


def _default_spot_factory(_bot_id: str, config: dict[str, Any]) -> Any:
    from quant_rd_tool.binance_bot import BinanceBot, BotConfig

    return BinanceBot(BotConfig(**config))


def _default_perp_factory(_bot_id: str, config: dict[str, Any]) -> Any:
    from quant_rd_tool.binance_perp_bot import BinancePerpBot, PerpBotConfig

    return BinancePerpBot(PerpBotConfig(**config))


class BotScheduler:
    def __init__(self) -> None:
        self._bots: dict[str, ManagedBot] = {}
        self._lock = threading.Lock()
        self._factories: dict[BotKind, BotFactory] = {
            "spot": _default_spot_factory,
            "perp": _default_perp_factory,
        }

    def set_factory(self, kind: BotKind, factory: BotFactory) -> None:
        self._factories[kind] = factory

    def register(
        self,
        *,
        bot_id: str,
        kind: BotKind,
        config: dict[str, Any],
        interval_minutes: int = 60,
    ) -> ManagedBot:
        if interval_minutes < 1:
            raise ValueError("interval_minutes must be >= 1")
        with self._lock:
            existing = self._bots.get(bot_id)
            if existing and existing.status == "running":
                raise ValueError(f"bot '{bot_id}' 已在运行，先停止再修改")
            bot = ManagedBot(
                bot_id=bot_id, kind=kind, config=dict(config), interval_minutes=interval_minutes
            )
            self._bots[bot_id] = bot
            return bot

    def run_managed_once(self, bot_id: str) -> dict[str, Any]:
        """Execute one cycle synchronously; records result/error on the bot."""
        bot = self._get(bot_id)
        factory = self._factories.get(bot.kind)
        if factory is None:
            raise ValueError(f"未知机器人类型: {bot.kind}")
        bot.last_run_at = now_iso()
        try:
            instance = factory(bot_id, bot.config)
            result = instance.run_once()
            bot.run_count += 1
            bot.last_result = _trim_result(result)
            bot.last_error = None
            return result
        except Exception as e:  # noqa: BLE001 - surfaced via status
            bot.error_count += 1
            bot.last_error = str(e)
            bot.status = "error"
            logger.exception("Managed bot %s cycle failed", bot_id)
            raise

    def start(self, bot_id: str) -> dict[str, Any]:
        bot = self._get(bot_id)
        if bot.status == "running" and bot._thread and bot._thread.is_alive():
            return bot.public()
        bot._stop.clear()
        bot.status = "running"
        thread = threading.Thread(
            target=self._loop, args=(bot_id,), daemon=True, name=f"bot-{bot_id}"
        )
        bot._thread = thread
        thread.start()
        return bot.public()

    def stop(self, bot_id: str) -> dict[str, Any]:
        bot = self._get(bot_id)
        bot._stop.set()
        bot.status = "stopped"
        return bot.public()

    def remove(self, bot_id: str) -> dict[str, Any]:
        bot = self._get(bot_id)
        bot._stop.set()
        with self._lock:
            self._bots.pop(bot_id, None)
        return {"removed": bot_id}

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [b.public() for b in self._bots.values()]

    def status_one(self, bot_id: str) -> dict[str, Any]:
        return self._get(bot_id).public()

    def _get(self, bot_id: str) -> ManagedBot:
        with self._lock:
            bot = self._bots.get(bot_id)
        if bot is None:
            raise KeyError(f"未注册的机器人: {bot_id}")
        return bot

    def _loop(self, bot_id: str) -> None:
        bot = self._bots.get(bot_id)
        if bot is None:
            return
        while not bot._stop.is_set():
            started = time.time()
            try:
                self.run_managed_once(bot_id)
            except Exception:
                pass  # already recorded on the bot
            elapsed = time.time() - started
            wait = max(bot.interval_minutes * 60 - elapsed, 5)
            if bot._stop.wait(timeout=wait):
                break
        bot.status = "stopped"


def _trim_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep status payloads small: drop heavy nested analysis/curves."""
    if not isinstance(result, dict):
        return {"value": result}
    keep = {
        k: v
        for k, v in result.items()
        if k not in ("analysis", "equity_curve", "trades", "analysis_summary")
    }
    perf = result.get("performance")
    if isinstance(perf, dict):
        keep["performance"] = perf
    return keep


# Module-level singleton used by the API routes.
_SCHEDULER: BotScheduler | None = None


def get_scheduler() -> BotScheduler:
    global _SCHEDULER
    if _SCHEDULER is None:
        _SCHEDULER = BotScheduler()
    return _SCHEDULER
