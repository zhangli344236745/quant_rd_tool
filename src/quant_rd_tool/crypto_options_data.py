"""Binance European options (EAPI) — ATM IV snapshots and local history."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from quant_rd_tool.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL", "BNB")
EAPI_BASE = "https://eapi.binance.com"
_OPTION_RE = re.compile(r"^(?P<base>[A-Z0-9]+)-(?P<exp>\d{6})-(?P<strike>\d+(?:\.\d+)?)-(?P<side>[CP])$")


def options_iv_dir(data_dir: str | Path = "data/crypto") -> Path:
    return Path(data_dir) / "options_iv"


def history_path(base: str, data_dir: str | Path = "data/crypto") -> Path:
    return options_iv_dir(data_dir) / f"{base.upper()}.jsonl"


def _client() -> httpx.Client:
    proxies: dict[str, str] = {}
    if settings.http_proxy:
        proxies["http://"] = settings.http_proxy
    if settings.https_proxy:
        proxies["https://"] = settings.https_proxy
    kwargs: dict[str, Any] = {"timeout": 20.0, "follow_redirects": True}
    if proxies:
        kwargs["proxy"] = settings.https_proxy or settings.http_proxy
    return httpx.Client(**kwargs)


def fetch_mark_rows(*, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """GET /eapi/v1/mark — mark IV per option symbol."""
    own = client is None
    c = client or _client()
    try:
        r = c.get(f"{EAPI_BASE}/eapi/v1/mark")
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            raise ValueError(f"unexpected mark payload: {type(data)}")
        return data
    finally:
        if own:
            c.close()


def _underlying_param(base: str) -> str:
    """Binance EAPI expects ``underlying=BTCUSDT`` (not bare BTC)."""
    b = base.strip().upper()
    if b.endswith("USDT"):
        return b
    return f"{b}USDT"


def fetch_index_price(
    base: str,
    *,
    client: httpx.Client | None = None,
) -> float | None:
    """GET /eapi/v1/index?underlying=BTCUSDT — single underlying index."""
    own = client is None
    c = client or _client()
    try:
        r = c.get(
            f"{EAPI_BASE}/eapi/v1/index",
            params={"underlying": _underlying_param(base)},
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            raw = data.get("indexPrice") or data.get("price")
            if raw is not None:
                return float(raw)
        return None
    except httpx.HTTPError as e:
        logger.warning("eapi index failed for %s: %s", base, e)
        return None
    finally:
        if own:
            c.close()


def fetch_index_prices(
    bases: list[str] | None = None,
    *,
    client: httpx.Client | None = None,
) -> dict[str, float]:
    """Underlying index prices keyed by base asset (BTC, ETH, ...)."""
    symbols = [s.upper() for s in (bases or list(DEFAULT_SYMBOLS))]
    own = client is None
    c = client or _client()
    out: dict[str, float] = {}
    try:
        for base in symbols:
            px = fetch_index_price(base, client=c)
            if px is not None:
                out[base] = px
    finally:
        if own:
            c.close()
    return out


def parse_option_symbol(symbol: str) -> dict[str, Any] | None:
    m = _OPTION_RE.match(symbol.strip().upper())
    if not m:
        return None
    exp_raw = m.group("exp")
    try:
        expiry = datetime.strptime(exp_raw, "%y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    return {
        "base": m.group("base"),
        "expiry": expiry,
        "strike": float(m.group("strike")),
        "side": m.group("side"),
        "symbol": symbol.upper(),
    }


def pick_atm_contract(
    marks: list[dict[str, Any]],
    base: str,
    index_price: float,
    *,
    min_days: int = 7,
    target_days: int = 30,
) -> dict[str, Any] | None:
    """Choose near-month ATM call (fallback put) by strike distance and DTE."""
    now = datetime.now(UTC)
    candidates: list[dict[str, Any]] = []
    for row in marks:
        sym = str(row.get("symbol") or "")
        meta = parse_option_symbol(sym)
        if not meta or meta["base"] != base.upper():
            continue
        dte = (meta["expiry"] - now).total_seconds() / 86400
        if dte < min_days:
            continue
        iv_raw = row.get("markIV") or row.get("askIV") or row.get("bidIV")
        if iv_raw is None:
            continue
        try:
            iv = float(iv_raw)
        except (TypeError, ValueError):
            continue
        if iv <= 0 or iv > 5:
            continue
        candidates.append(
            {
                **meta,
                "dte": dte,
                "iv": iv,
                "mark_price": row.get("markPrice"),
                "bid_iv": row.get("bidIV"),
                "ask_iv": row.get("askIV"),
            }
        )
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
        "symbol": best["symbol"],
        "contract": best["symbol"],
        "expiry": best["expiry"].isoformat(),
        "strike": best["strike"],
        "side": best["side"],
        "dte": round(best["dte"], 2),
        "atm_iv": round(best["iv"], 6),
        "underlying_price": round(index_price, 4),
        "mark_price": best.get("mark_price"),
    }


def append_snapshot(row: dict[str, Any], *, data_dir: str | Path = "data/crypto") -> Path:
    base = str(row["base"]).upper()
    path = history_path(base, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def load_history(
    base: str,
    *,
    data_dir: str | Path = "data/crypto",
    limit: int = 500,
) -> list[dict[str, Any]]:
    path = history_path(base, data_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def fetch_atm_iv_snapshot(
    bases: list[str] | None = None,
    *,
    data_dir: str | Path = "data/crypto",
    persist: bool = True,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch ATM IV per underlying; optionally persist to JSONL."""
    symbols = [s.upper() for s in (bases or list(DEFAULT_SYMBOLS))]
    own = client is None
    c = client or _client()
    try:
        marks = fetch_mark_rows(client=c)
        indices = fetch_index_prices(symbols, client=c)
    finally:
        if own:
            c.close()

    ts = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []
    for base in symbols:
        idx = indices.get(base)
        if idx is None:
            rows.append(
                {
                    "base": base,
                    "ts": ts,
                    "error": "index price unavailable",
                    "atm_iv": None,
                }
            )
            continue
        atm = pick_atm_contract(marks, base, idx)
        if not atm:
            rows.append(
                {
                    "base": base,
                    "ts": ts,
                    "error": "no ATM option contract found",
                    "atm_iv": None,
                    "underlying_price": idx,
                }
            )
            continue
        row = {
            "base": base,
            "ts": ts,
            **atm,
        }
        rows.append(row)
        if persist:
            append_snapshot(row, data_dir=data_dir)
    return rows
