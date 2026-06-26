"""Built-in interval runner for crypto market radar scans."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from quant_rd_tool.crypto_market_radar import load_config
from quant_rd_tool.crypto_market_radar_scheduler import run_market_radar_scan_cycle
from quant_rd_tool.time_util import now_iso

logger = logging.getLogger(__name__)


class MarketRadarRunner:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.run_count = 0
        self.last_run_at: str | None = None
        self.last_error: str | None = None
        self.last_result: dict[str, Any] | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def public(self) -> dict[str, Any]:
        return {
            "running": self.is_running(),
            "run_count": self.run_count,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "last_result": self.last_result,
        }

    def start(self) -> dict[str, Any]:
        if self.is_running():
            return self.public()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="market-radar", daemon=True)
        self._thread.start()
        return self.public()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        return self.public()

    def run_once(self) -> dict[str, Any]:
        try:
            result = run_market_radar_scan_cycle(force=True)
            self.run_count += 1
            self.last_run_at = now_iso()
            self.last_error = None
            self.last_result = {
                "binance_new_count": result.get("binance_new_count"),
                "coingecko_new_count": result.get("coingecko_new_count"),
                "high_volatility_flagged_count": result.get("high_volatility_flagged_count"),
            }
            return result
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            if isinstance(e, httpx.HTTPError):
                logger.warning("Market radar scan failed: %s", e)
            else:
                logger.exception("Market radar scan failed")
            raise

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            try:
                self.run_once()
            except Exception:
                pass
            try:
                cfg = load_config()
                wait_s = max(int(cfg.builtin_interval_sec), 60)
            except Exception:
                wait_s = 600
            elapsed = time.time() - started
            sleep_s = max(wait_s - elapsed, 1.0)
            if self._stop.wait(timeout=sleep_s):
                break


_RUNNER: MarketRadarRunner | None = None


def get_market_radar_runner() -> MarketRadarRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = MarketRadarRunner()
    return _RUNNER


def boot_market_radar_if_enabled() -> None:
    cfg = load_config()
    if cfg.builtin_scan_enabled:
        get_market_radar_runner().start()
