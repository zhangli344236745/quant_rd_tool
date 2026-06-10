"""Deribit options market data — public REST API."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from quant_rd_tool.config import settings

logger = logging.getLogger(__name__)

DERIBIT_API = "https://www.deribit.com/api/v2"
DERIBIT_SYMBOLS = ("BTC", "ETH", "SOL", "BNB")
_OPTION_RE = re.compile(
    r"^(?P<base>[A-Z0-9]+)-(?P<exp>\d{1,2}[A-Z]{3}\d{2})-(?P<strike>\d+(?:\.\d+)?)-(?P<side>[CP])$"
)
_INDEX_NAMES = {
    "BTC": "btc_usd",
    "ETH": "eth_usd",
    "SOL": "sol_usd",
    "BNB": "bnb_usd",
}


def _client() -> httpx.Client:
    kwargs: dict[str, Any] = {"timeout": 25.0, "follow_redirects": True}
    proxy = settings.https_proxy or settings.http_proxy
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


def normalize_mark_iv(raw: Any) -> float | None:
    """Deribit mark_iv is usually percent (e.g. 52.3); Binance uses decimal."""
    try:
        iv = float(raw)
    except (TypeError, ValueError):
        return None
    if iv <= 0:
        return None
    if iv > 3:
        iv = iv / 100.0
    if iv > 3:
        return None
    return round(iv, 6)


def parse_deribit_instrument(name: str) -> dict[str, Any] | None:
    m = _OPTION_RE.match(name.strip().upper())
    if not m:
        return None
    try:
        expiry = datetime.strptime(m.group("exp"), "%d%b%y").replace(tzinfo=UTC)
    except ValueError:
        return None
    return {
        "base": m.group("base"),
        "expiry": expiry,
        "strike": float(m.group("strike")),
        "side": m.group("side"),
        "symbol": name.upper(),
    }


def fetch_book_summary(
    currency: str,
    *,
    kind: str = "option",
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """GET /public/get_book_summary_by_currency."""
    own = client is None
    c = client or _client()
    try:
        r = c.get(
            f"{DERIBIT_API}/public/get_book_summary_by_currency",
            params={"currency": currency.upper(), "kind": kind},
        )
        r.raise_for_status()
        payload = r.json()
        result = payload.get("result")
        if not isinstance(result, list):
            raise ValueError(f"unexpected deribit summary: {type(result)}")
        return result
    finally:
        if own:
            c.close()


def fetch_index_price(
    base: str,
    *,
    client: httpx.Client | None = None,
) -> float | None:
    index_name = _INDEX_NAMES.get(base.upper())
    if not index_name:
        return None
    own = client is None
    c = client or _client()
    try:
        r = c.get(
            f"{DERIBIT_API}/public/get_index_price",
            params={"index_name": index_name},
        )
        r.raise_for_status()
        data = r.json().get("result") or {}
        raw = data.get("index_price")
        return float(raw) if raw is not None else None
    except (httpx.HTTPError, TypeError, ValueError) as e:
        logger.warning("deribit index failed for %s: %s", base, e)
        return None
    finally:
        if own:
            c.close()


def _rows_to_candidates(
    rows: list[dict[str, Any]],
    base: str,
    index_price: float,
    *,
    min_days: int = 7,
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    base_u = base.upper()
    out: list[dict[str, Any]] = []
    for row in rows:
        sym = str(row.get("instrument_name") or "")
        meta = parse_deribit_instrument(sym)
        if not meta or meta["base"] != base_u:
            continue
        iv = normalize_mark_iv(row.get("mark_iv"))
        if iv is None:
            continue
        dte = (meta["expiry"] - now).total_seconds() / 86400.0
        if dte < min_days:
            continue
        out.append(
            {
                **meta,
                "dte": dte,
                "iv": iv,
                "mark_price": row.get("mark_price"),
                "open_interest": row.get("open_interest"),
                "underlying_price": row.get("underlying_price"),
            }
        )
    return out


def pick_atm_contract(
    rows: list[dict[str, Any]],
    base: str,
    index_price: float,
    *,
    min_days: int = 7,
    target_days: int = 30,
) -> dict[str, Any] | None:
    """Near-month ATM call on Deribit (same scoring as Binance helper)."""
    candidates = _rows_to_candidates(rows, base, index_price, min_days=min_days)
    if not candidates:
        return None

    calls = [c for c in candidates if c["side"] == "C"]
    pool = calls if calls else candidates

    def score(c: dict[str, Any]) -> tuple[float, float]:
        strike_dist = abs(c["strike"] - index_price) / max(index_price, 1e-9)
        dte_dist = abs(c["dte"] - target_days)
        return (strike_dist, dte_dist)

    best = min(pool, key=score)
    return {
        "venue": "deribit",
        "symbol": best["symbol"],
        "contract": best["symbol"],
        "expiry": best["expiry"].isoformat(),
        "strike": best["strike"],
        "side": best["side"],
        "dte": round(best["dte"], 2),
        "atm_iv": round(best["iv"], 6),
        "underlying_price": round(index_price, 4),
        "mark_price": best.get("mark_price"),
        "open_interest": best.get("open_interest"),
    }


def fetch_atm_iv_snapshot(
    bases: list[str] | None = None,
    *,
    min_days: int = 7,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """ATM IV per underlying from Deribit option book summaries."""
    symbols = [s.upper() for s in (bases or DERIBIT_SYMBOLS)]
    ts = datetime.now(UTC).isoformat()
    own = client is None
    c = client or _client()
    rows: list[dict[str, Any]] = []
    try:
        for base in symbols:
            idx = fetch_index_price(base, client=c)
            if idx is None:
                rows.append(
                    {
                        "base": base,
                        "venue": "deribit",
                        "ts": ts,
                        "error": "index price unavailable",
                        "atm_iv": None,
                    }
                )
                continue
            try:
                summary = fetch_book_summary(base, client=c)
            except httpx.HTTPError as e:
                rows.append(
                    {
                        "base": base,
                        "venue": "deribit",
                        "ts": ts,
                        "error": str(e),
                        "atm_iv": None,
                    }
                )
                continue
            atm = pick_atm_contract(summary, base, idx, min_days=min_days)
            if not atm:
                rows.append(
                    {
                        "base": base,
                        "venue": "deribit",
                        "ts": ts,
                        "error": "no ATM option contract found",
                        "atm_iv": None,
                        "underlying_price": idx,
                    }
                )
                continue
            rows.append({"base": base, "ts": ts, **atm})
    finally:
        if own:
            c.close()
    return rows
