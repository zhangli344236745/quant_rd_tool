"""Polymarket book cache with fast REST polling (stream_mode websocket/hybrid)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

_book_cache: dict[str, dict[str, Any]] = {}
_cache_lock = threading.Lock()
_dirty = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_last_poll_at: str | None = None
_last_error: str | None = None
_mode = "rest"
_token_ids: list[str] = []


def get_book_cache(token_id: str) -> dict[str, Any] | None:
    with _cache_lock:
        return _book_cache.get(token_id)


def is_dirty() -> bool:
    return _dirty.is_set()


def consume_dirty() -> bool:
    if _dirty.is_set():
        _dirty.clear()
        return True
    return False


def get_stream_status() -> dict[str, Any]:
    return {
        "mode": _mode,
        "running": _thread is not None and _thread.is_alive(),
        "cached_books": len(_book_cache),
        "token_count": len(_token_ids),
        "last_poll_at": _last_poll_at,
        "last_error": _last_error,
        "degraded": _mode in ("websocket", "hybrid") and _last_error is not None,
    }


def _poll_loop(interval_s: float, http_get: Callable[..., Any]) -> None:
    global _last_poll_at, _last_error
    from quant_rd_tool.crypto_polymarket_arb import fetch_clob_book
    from quant_rd_tool.time_util import now_iso

    while not _stop.is_set():
        ids = list(_token_ids)
        if not ids:
            _stop.wait(interval_s)
            continue
        err: str | None = None
        for tid in ids:
            if _stop.is_set():
                break
            try:
                book = fetch_clob_book(tid, http_get=http_get)
                with _cache_lock:
                    _book_cache[tid] = book
                _dirty.set()
            except Exception as e:  # noqa: BLE001
                err = str(e)
        _last_poll_at = now_iso()
        _last_error = err
        _stop.wait(interval_s)


def start_stream(
    token_ids: list[str],
    *,
    mode: str = "rest",
    poll_interval_s: float = 5.0,
    http_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    global _thread, _mode, _token_ids
    stop_stream()
    _mode = mode if mode in ("rest", "websocket", "hybrid") else "rest"
    _token_ids = [str(t) for t in token_ids if str(t).strip()]
    if _mode == "rest" or not _token_ids:
        return get_stream_status()
    from quant_rd_tool.crypto_polymarket_arb import _default_http_get

    getter = http_get or _default_http_get
    _stop.clear()
    _thread = threading.Thread(
        target=_poll_loop,
        args=(max(poll_interval_s, 2.0), getter),
        name="polymarket-book-stream",
        daemon=True,
    )
    _thread.start()
    return get_stream_status()


def stop_stream() -> dict[str, Any]:
    global _thread
    _stop.set()
    if _thread:
        _thread.join(timeout=3)
    _thread = None
    _stop.clear()
    return get_stream_status()


def resolve_watchlist_token_ids(cfg: Any) -> list[str]:
    from quant_rd_tool.crypto_polymarket_arb import fetch_gamma_markets, load_latest_scan

    ids: set[str] = set()
    for cid in cfg.watchlist_condition_ids or []:
        for m in fetch_gamma_markets(condition_ids=[cid], use_cache=True):
            if m.get("yes_token_id"):
                ids.add(str(m["yes_token_id"]))
    scan = load_latest_scan()
    for row in (scan or {}).get("items") or []:
        if row.get("yes_token_id"):
            ids.add(str(row["yes_token_id"]))
    return list(ids)
