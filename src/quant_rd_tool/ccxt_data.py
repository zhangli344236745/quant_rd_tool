"""Fetch crypto OHLCV via ccxt (Binance spot by default)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Literal

import pandas as pd

from quant_rd_tool.crypto_time import ms_to_beijing_naive

logger = logging.getLogger(__name__)

ExchangeId = Literal["binance", "okx", "bybit"]
MarketType = Literal["spot", "future"]

# bare symbol -> ccxt unified symbol
_SYMBOL_MAP = {
    "BTC": "BTC/USDT",
    "ETH": "ETH/USDT",
    "BNB": "BNB/USDT",
    "SOL": "SOL/USDT",
    "XRP": "XRP/USDT",
    "DOGE": "DOGE/USDT",
}


def to_ccxt_symbol(symbol: str, quote: str = "USDT") -> str:
    """BTC / BTCUSDT / BTC/USDT -> BTC/USDT."""
    s = symbol.strip().upper().replace("-", "/")
    if "/" in s:
        return s
    if s.endswith(quote) and len(s) > len(quote):
        base = s[: -len(quote)]
        return f"{base}/{quote}"
    return _SYMBOL_MAP.get(s, f"{s}/{quote}")


def to_qlib_code(symbol: str) -> str:
    """BTC/USDT -> CRYPTO_BTC."""
    base = to_ccxt_symbol(symbol).split("/")[0]
    return f"CRYPTO_{base}"


def timeframe_to_ms(timeframe: str) -> int:
    """ccxt timeframe string -> milliseconds per bar."""
    tf = timeframe.strip().lower()
    if tf.endswith("ms"):
        return int(tf[:-2])
    if tf.endswith("m"):
        return int(tf[:-1]) * 60_000
    if tf.endswith("h"):
        return int(tf[:-1]) * 3_600_000
    if tf.endswith("d"):
        return int(tf[:-1]) * 86_400_000
    if tf.endswith("w"):
        return int(tf[:-1]) * 7 * 86_400_000
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def timeframe_to_qlib_freq(timeframe: str) -> str:
    """Map ccxt timeframe to qlib calendar/bin freq name."""
    tf = timeframe.strip().lower()
    if tf in ("1d", "day", "d"):
        return "day"
    if tf.endswith("m"):
        return f"{tf[:-1]}min"
    if tf.endswith("h"):
        return f"{tf[:-1]}min" if int(tf[:-1]) < 60 else f"{int(tf[:-1]) // 60}h"
    return tf


def _rows_to_df(rows: list, symbol: str) -> pd.DataFrame:
    cols = ["timestamp", "date", "symbol", "open", "high", "low", "close", "volume"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = df["timestamp"].astype("int64")
    df["date"] = df["timestamp"].map(ms_to_beijing_naive)
    df["symbol"] = to_qlib_code(symbol)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[cols].dropna(subset=["close"])


def create_exchange(
    exchange_id: ExchangeId = "binance",
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    testnet: bool = False,
    api_base: str | None = None,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
    market_type: MarketType = "spot",
):
    import ccxt

    klass = getattr(ccxt, exchange_id)
    opts: dict = {"enableRateLimit": True}
    if exchange_id == "binance":
        # ccxt binance may fetch spot+fapi+dapi markets by default; that can fail
        # in restricted networks. Limit market discovery to the requested type.
        fetch_markets = ["spot"] if market_type == "spot" else ["future"]
        opts["options"] = {"defaultType": market_type, "fetchMarkets": fetch_markets}
        if testnet:
            opts["options"]["sandboxMode"] = True
    ex = klass(opts)
    if http_proxy or https_proxy:
        ex.proxies = {}
        if http_proxy:
            ex.proxies["http"] = http_proxy
        if https_proxy:
            ex.proxies["https"] = https_proxy
    if api_base and exchange_id == "binance":
        # Allow overriding Binance REST endpoint, e.g. https://api1.binance.com
        try:
            ex.urls["api"] = {"public": api_base, "private": api_base}
        except Exception:
            pass
    if api_key and api_secret:
        ex.apiKey = api_key
        ex.secret = api_secret
    if testnet and exchange_id == "binance":
        ex.set_sandbox_mode(True)
    return ex


def fetch_ohlcv(
    symbol: str,
    *,
    timeframe: str = "1d",
    limit: int = 500,
    exchange_id: ExchangeId = "binance",
    since_ms: int | None = None,
) -> pd.DataFrame:
    """Public OHLCV (no API key required on Binance)."""
    from quant_rd_tool.config import settings

    ex = create_exchange(
        exchange_id,
        api_base=settings.binance_api_base if exchange_id == "binance" else None,
        http_proxy=settings.http_proxy,
        https_proxy=settings.https_proxy,
        market_type="spot",
    )
    pair = to_ccxt_symbol(symbol)
    since = since_ms
    if since is None and timeframe == "1d":
        since = int((datetime.now(UTC).timestamp() - limit * 86400) * 1000)

    rows: list = []
    try:
        batch = ex.fetch_ohlcv(pair, timeframe=timeframe, since=since, limit=min(limit, 1000))
        rows.extend(batch or [])
    except Exception as e:
        msg = f"ccxt fetch_ohlcv failed for {pair}: {e}"
        raise ConnectionError(msg) from e
    finally:
        try:
            ex.close()
        except Exception:
            pass

    if not rows:
        msg = f"No OHLCV for {pair}"
        raise ValueError(msg)

    return _rows_to_df(rows, symbol)


def fetch_ohlcv_history(
    symbol: str,
    *,
    timeframe: str = "5m",
    since_ms: int,
    until_ms: int | None = None,
    exchange_id: ExchangeId = "binance",
    max_bars: int | None = None,
) -> pd.DataFrame:
    """Paginated OHLCV fetch from ``since_ms`` (inclusive) forward."""
    from quant_rd_tool.config import settings

    ex = create_exchange(
        exchange_id,
        api_base=settings.binance_api_base if exchange_id == "binance" else None,
        http_proxy=settings.http_proxy,
        https_proxy=settings.https_proxy,
    )
    pair = to_ccxt_symbol(symbol)
    bar_ms = timeframe_to_ms(timeframe)
    until = until_ms or int(datetime.now(UTC).timestamp() * 1000)
    cursor = since_ms
    all_rows: list = []

    try:
        while cursor < until:
            batch = ex.fetch_ohlcv(pair, timeframe=timeframe, since=cursor, limit=1000)
            if not batch:
                break
            all_rows.extend(batch)
            last_ts = batch[-1][0]
            next_cursor = last_ts + bar_ms
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if max_bars and len(all_rows) >= max_bars:
                all_rows = all_rows[:max_bars]
                break
            if len(batch) < 1000:
                break
            time.sleep(ex.rateLimit / 1000 if ex.rateLimit else 0.2)
    except Exception as e:
        msg = f"ccxt fetch_ohlcv_history failed for {pair}: {e}"
        raise ConnectionError(msg) from e
    finally:
        try:
            ex.close()
        except Exception:
            pass

    if not all_rows:
        msg = f"No OHLCV history for {pair} since {since_ms}"
        raise ValueError(msg)

    return _rows_to_df(all_rows, symbol)


def fetch_ohlcv_incremental(
    symbol: str,
    *,
    timeframe: str,
    last_timestamp_ms: int,
    exchange_id: ExchangeId = "binance",
    limit: int = 1000,
) -> pd.DataFrame:
    """
    Fetch new bars after ``last_timestamp_ms``, plus refresh the latest exchange tail.

    Uses ``since`` for gaps, then always merges the most recent ~20 bars from the
    exchange (including the in-progress 5m candle) so local data stays current.
    """
    bar_ms = timeframe_to_ms(timeframe)
    since_ms = last_timestamp_ms + bar_ms
    from quant_rd_tool.config import settings

    ex = create_exchange(
        exchange_id,
        api_base=settings.binance_api_base if exchange_id == "binance" else None,
        http_proxy=settings.http_proxy,
        https_proxy=settings.https_proxy,
    )
    pair = to_ccxt_symbol(symbol)
    collected: dict[int, list] = {}
    try:
        batch = ex.fetch_ohlcv(pair, timeframe=timeframe, since=since_ms, limit=min(limit, 1000))
        for row in batch or []:
            if row[0] > last_timestamp_ms:
                collected[row[0]] = row
        # Latest window from exchange (no ``since``): refresh last bar + add open candle.
        tail = ex.fetch_ohlcv(pair, timeframe=timeframe, limit=20)
        for row in tail or []:
            if row[0] >= last_timestamp_ms:
                collected[row[0]] = row
    except Exception as e:
        msg = f"ccxt incremental fetch failed for {pair}: {e}"
        raise ConnectionError(msg) from e
    finally:
        try:
            ex.close()
        except Exception:
            pass

    if not collected:
        return _rows_to_df([], symbol)
    return _rows_to_df(sorted(collected.values(), key=lambda r: r[0]), symbol)
