"""Perp account analytics (balances, trades, daily pnl) for ops dashboards."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Literal, TypeVar

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.config import settings

logger = logging.getLogger(__name__)

IncomeType = Literal["REALIZED_PNL", "FUNDING_FEE", "COMMISSION"]

T = TypeVar("T")


def _with_retry(fn: Callable[[], T], *, attempts: int = 3, base_delay_sec: float = 0.4) -> T:
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e).lower()
            retryable = any(
                token in msg
                for token in (
                    "rate limit",
                    "too many",
                    "429",
                    "timeout",
                    "timed out",
                    "network",
                    "ddos",
                    "invalidnonce",
                    "recvwindow",
                )
            )
            if not retryable or i >= attempts - 1:
                raise
            time.sleep(base_delay_sec * (2**i))
    assert last_err is not None
    raise last_err


def _exchange(*, testnet: bool = False):
    if not (settings.binance_api_key and settings.binance_api_secret):
        return None
    ex = cxt.create_exchange(
        "binance",
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        testnet=testnet or settings.binance_testnet,
        api_base=settings.binance_api_base,
        http_proxy=settings.http_proxy,
        https_proxy=settings.https_proxy,
        market_type="future",
    )
    try:
        if getattr(ex, "load_time_difference", None):
            ex.load_time_difference()
    except Exception:
        pass
    return ex


def fetch_future_balances(*, testnet: bool = False) -> dict[str, Any]:
    """Return normalized balance snapshot for futures account."""
    ex = _exchange(testnet=testnet)
    if ex is None:
        return {"enabled": False, "error": "missing api key/secret", "items": []}
    try:
        try:
            bal = ex.fetch_balance({"type": "future"})
        except Exception:
            bal = ex.fetch_balance()

        # ccxt shapes differ; prefer balances dict if present
        items: list[dict[str, Any]] = []
        balances = bal.get("total") if isinstance(bal, dict) else None
        free = bal.get("free") if isinstance(bal, dict) else None
        used = bal.get("used") if isinstance(bal, dict) else None

        if isinstance(balances, dict):
            for asset, total in balances.items():
                if total is None:
                    continue
                t = float(total or 0)
                f = float((free or {}).get(asset) or 0) if isinstance(free, dict) else None
                u = float((used or {}).get(asset) or 0) if isinstance(used, dict) else None
                if abs(t) <= 1e-12 and (f is None or abs(f) <= 1e-12) and (u is None or abs(u) <= 1e-12):
                    continue
                items.append(
                    {
                        "asset": asset,
                        "total": t,
                        "available": f,
                        "used": u,
                    }
                )

        # Binance futures also exposes account-level fields inside info
        info = bal.get("info") if isinstance(bal, dict) else None
        summary = {}
        if isinstance(info, dict):
            # Common fields in futures account response
            for k in (
                "totalWalletBalance",
                "availableBalance",
                "totalUnrealizedProfit",
                "totalMarginBalance",
                "totalInitialMargin",
                "totalMaintMargin",
            ):
                v = info.get(k)
                if v is not None and v != "":
                    try:
                        summary[k] = float(v)
                    except Exception:
                        summary[k] = v

        return {"enabled": True, "summary": summary, "items": sorted(items, key=lambda x: x["asset"])}
    finally:
        try:
            ex.close()
        except Exception:
            pass


def fetch_recent_trades(
    *,
    base: str,
    quote: str = "USDT",
    limit: int = 50,
    since_ms: int | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    ex = _exchange(testnet=testnet)
    if ex is None:
        return {"enabled": False, "error": "missing api key/secret", "items": []}
    symbol = f"{base.strip().upper()}/{quote.strip().upper()}:{quote.strip().upper()}"
    try:
        trades = _with_retry(
            lambda: ex.fetch_my_trades(symbol, since_ms, min(int(limit), 200), {"type": "future"}),
        )
        items: list[dict[str, Any]] = []
        for t in trades or []:
            items.append(
                {
                    "ts": (
                        datetime.fromtimestamp((t.get("timestamp") or 0) / 1000, tz=UTC).isoformat()
                        if t.get("timestamp")
                        else None
                    ),
                    "symbol": t.get("symbol") or symbol,
                    "side": t.get("side"),
                    "type": t.get("type"),
                    "price": t.get("price"),
                    "qty": t.get("amount"),
                    "fee": (t.get("fee") or {}).get("cost") if isinstance(t.get("fee"), dict) else None,
                    "fee_asset": (t.get("fee") or {}).get("currency") if isinstance(t.get("fee"), dict) else None,
                    "orderId": t.get("order"),
                    "tradeId": t.get("id"),
                    "raw": (t.get("info") or {}) if isinstance(t.get("info"), dict) else t.get("info"),
                }
            )
        return {"enabled": True, "symbol": symbol, "count": len(items), "items": items}
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_recent_trades failed for %s: %s", symbol, e)
        return {"enabled": True, "symbol": symbol, "count": 0, "items": [], "error": str(e)}
    finally:
        try:
            ex.close()
        except Exception:
            pass


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fetch_daily_pnl(
    *,
    days: int = 7,
    testnet: bool = False,
) -> dict[str, Any]:
    """
    Aggregate daily net pnl from Binance futures income history:
    net = realized + funding + fees.
    """
    ex = _exchange(testnet=testnet)
    if ex is None:
        return {"enabled": False, "error": "missing api key/secret", "items": []}
    d = max(1, min(int(days), 60))
    end = datetime.now(UTC)
    start = end - timedelta(days=d)
    try:
        fn = getattr(ex, "fapiPrivateGetIncome", None) or getattr(ex, "fapiPrivateV1GetIncome", None)
        if not fn:
            return {"enabled": True, "error": "income endpoint unavailable", "items": []}

        # Pull all types; keep window inclusive.
        all_rows: list[dict[str, Any]] = []
        for it in ("REALIZED_PNL", "FUNDING_FEE", "COMMISSION"):
            try:
                rows = fn({"incomeType": it, "startTime": _ms(start), "endTime": _ms(end)})
                if isinstance(rows, list):
                    all_rows.extend(rows)
            except Exception:
                continue

        by_day: dict[str, dict[str, float]] = defaultdict(lambda: {"REALIZED_PNL": 0.0, "FUNDING_FEE": 0.0, "COMMISSION": 0.0})
        for r in all_rows:
            ts = r.get("time")
            income = r.get("income")
            if ts is None or income is None:
                continue
            try:
                day = datetime.fromtimestamp(int(ts) / 1000, tz=UTC).date().isoformat()
                val = float(income)
            except Exception:
                continue
            t = str(r.get("incomeType") or "")
            if t not in ("REALIZED_PNL", "FUNDING_FEE", "COMMISSION"):
                continue
            by_day[day][t] += val

        items: list[dict[str, Any]] = []
        for day in sorted(by_day.keys()):
            realized = by_day[day]["REALIZED_PNL"]
            funding = by_day[day]["FUNDING_FEE"]
            fees = by_day[day]["COMMISSION"]
            net = realized + funding + fees
            items.append(
                {
                    "day": day,
                    "realizedPnl": round(realized, 8),
                    "funding": round(funding, 8),
                    "fees": round(fees, 8),
                    "net": round(net, 8),
                }
            )
        return {"enabled": True, "start": start.isoformat(), "end": end.isoformat(), "count": len(items), "items": items}
    finally:
        try:
            ex.close()
        except Exception:
            pass

