"""Built-in interval runner for Polymarket arbitrage scans."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

from quant_rd_tool.crypto_polymarket_arb import load_config
from quant_rd_tool.crypto_polymarket_scheduler import run_polymarket_scan_cycle

logger = logging.getLogger(__name__)


class PolymarketArbRunner:
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
        try:
            cfg = load_config()
            if cfg.stream_mode in ("websocket", "hybrid"):
                from quant_rd_tool.crypto_polymarket_stream import resolve_watchlist_token_ids, start_stream

                start_stream(
                    resolve_watchlist_token_ids(cfg),
                    mode=cfg.stream_mode,
                    poll_interval_s=cfg.stream_poll_interval_s,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("polymarket stream start: %s", e)
        self._thread = threading.Thread(target=self._loop, name="polymarket-arb", daemon=True)
        self._thread.start()
        return self.public()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        try:
            from quant_rd_tool.crypto_polymarket_stream import stop_stream

            stop_stream()
        except Exception:  # noqa: BLE001
            pass
        return self.public()

    def run_once(self) -> dict[str, Any]:
        try:
            result = run_polymarket_scan_cycle(force=True)
            self.run_count += 1
            self.last_run_at = now_iso()
            self.last_error = None
            self.last_result = {
                "opportunities_count": result.get("opportunities_count"),
                "best_edge_bps": result.get("best_edge_bps"),
            }
            return result
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Polymarket scan failed")
            raise

    def _loop(self) -> None:
        from quant_rd_tool.crypto_polymarket_stream import consume_dirty

        last_scan_at = 0.0

        while not self._stop.is_set():
            started = time.time()
            try:
                cfg = load_config()
                stream_active = cfg.stream_mode in ("websocket", "hybrid")
                dirty = consume_dirty() if stream_active else False
                interval_due = (started - last_scan_at) >= max(int(cfg.builtin_interval_sec), 30)
                debounce_ok = (started - last_scan_at) >= float(cfg.stream_debounce_s)
                if interval_due or (stream_active and dirty and debounce_ok):
                    self.run_once()
                    last_scan_at = time.time()
            except Exception:
                pass
            try:
                cfg = load_config()
                wait_s = max(int(cfg.builtin_interval_sec), 30)
                if cfg.stream_mode in ("websocket", "hybrid"):
                    wait_s = min(wait_s, max(int(cfg.stream_poll_interval_s * 2), 10))
            except Exception:
                wait_s = 300
            elapsed = time.time() - started
            sleep_s = max(wait_s - elapsed, 1.0)
            if self._stop.wait(timeout=sleep_s):
                break


_RUNNER: PolymarketArbRunner | None = None


def get_polymarket_runner() -> PolymarketArbRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = PolymarketArbRunner()
    return _RUNNER


def boot_polymarket_scheduler_if_enabled() -> None:
    cfg = load_config()
    if cfg.builtin_scan_enabled:
        get_polymarket_runner().start()
