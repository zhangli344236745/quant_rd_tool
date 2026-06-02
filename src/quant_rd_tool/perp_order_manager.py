"""Perp order management via ccxt (Binance USDT-M futures by default).

This is an ops tool: list open orders, cancel orders, close position, and
best-effort reconcile of native protection orders based on local state.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.config import settings
from quant_rd_tool.crypto_ops_control import get_crypto_ops
from quant_rd_tool.perp_exec import NativeProtectionParams, reconcile_native_protection
from quant_rd_tool.perp_state import PerpSymbolState

logger = logging.getLogger(__name__)

PositionSide = Literal["long", "short", "flat"]


def _market_id(ex, symbol: str) -> str:
    """Resolve exchange-specific market id (e.g. ETHUSDT)."""
    try:
        m = ex.market(symbol)
        mid = m.get("id") if isinstance(m, dict) else None
        if mid:
            return str(mid)
    except Exception:
        pass
    # Fallback for "ETH/USDT:USDT" -> "ETHUSDT"
    s = symbol.split(":")[0]
    base_quote = s.replace("/", "")
    return base_quote


def _require_auth() -> None:
    if not (settings.binance_api_key and settings.binance_api_secret):
        raise ValueError("需配置 BINANCE_API_KEY / BINANCE_API_SECRET 才能管理永续订单")


def _require_not_kill_switched() -> None:
    ops = get_crypto_ops()
    if ops.get("kill_switch"):
        raise ValueError("Kill Switch 已开启：禁止执行永续订单变更操作")


def _exchange(*, testnet: bool = False):
    _require_auth()
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
    # Best-effort mitigate Binance -1021 timestamp drift.
    try:
        if getattr(ex, "load_time_difference", None):
            ex.load_time_difference()
    except Exception:
        pass
    return ex


def _perp_symbol(base: str, quote: str = "USDT", *, ccxt_symbol: str | None = None) -> str:
    if ccxt_symbol and str(ccxt_symbol).strip():
        return str(ccxt_symbol).strip()
    # ccxt unified future symbol is often "BTC/USDT:USDT" on Binance USDT-M.
    b = str(base or "").strip().upper()
    q = str(quote or "USDT").strip().upper()
    return f"{b}/{q}:{q}"


def list_open_orders(
    *,
    base: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    symbol = _perp_symbol(base, quote, ccxt_symbol=ccxt_symbol)
    # Listing open orders is read-only; return a friendly payload when auth is missing
    # so the frontend can still render the panel.
    if not (settings.binance_api_key and settings.binance_api_secret):
        return {
            "enabled": False,
            "symbol": symbol,
            "count": 0,
            "items": [],
            "error": "需配置 BINANCE_API_KEY / BINANCE_API_SECRET 才能查询交易所 open orders",
        }
    ex = _exchange(testnet=testnet)
    try:
        orders = ex.fetch_open_orders(symbol, None, None, {"type": "future"})
        items = []
        for o in orders or []:
            items.append(
                {
                    "id": o.get("id"),
                    "clientOrderId": (o.get("clientOrderId") or (o.get("info") or {}).get("clientOrderId")),
                    "symbol": o.get("symbol") or symbol,
                    "type": o.get("type"),
                    "side": o.get("side"),
                    "status": o.get("status"),
                    "price": o.get("price"),
                    "amount": o.get("amount"),
                    "filled": o.get("filled"),
                    "remaining": o.get("remaining"),
                    "stopPrice": (o.get("stopPrice") or (o.get("info") or {}).get("stopPrice")),
                    "timestamp": o.get("timestamp"),
                }
            )
        return {"symbol": symbol, "count": len(items), "items": items}
    finally:
        try:
            ex.close()
        except Exception:
            pass


def cancel_order(
    *,
    base: str,
    order_id: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    _require_not_kill_switched()
    symbol = _perp_symbol(base, quote, ccxt_symbol=ccxt_symbol)
    ex = _exchange(testnet=testnet)
    try:
        out = ex.cancel_order(str(order_id), symbol, {"type": "future"})
        return {"symbol": symbol, "cancelled": True, "result": out}
    finally:
        try:
            ex.close()
        except Exception:
            pass


def cancel_all_orders(
    *,
    base: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    _require_not_kill_switched()
    symbol = _perp_symbol(base, quote, ccxt_symbol=ccxt_symbol)
    ex = _exchange(testnet=testnet)
    try:
        cancelled: list[str] = []
        errors: list[dict[str, Any]] = []
        orders = ex.fetch_open_orders(symbol, None, None, {"type": "future"})
        for o in orders or []:
            oid = str(o.get("id") or "")
            if not oid:
                continue
            try:
                ex.cancel_order(oid, symbol, {"type": "future"})
                cancelled.append(oid)
            except Exception as e:
                errors.append({"id": oid, "error": str(e)})
        return {"symbol": symbol, "cancelled": cancelled, "errors": errors, "count": len(cancelled)}
    finally:
        try:
            ex.close()
        except Exception:
            pass


def close_position_market(
    *,
    base: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    """Best-effort reduceOnly market close based on exchange position amount."""
    _require_not_kill_switched()
    symbol = _perp_symbol(base, quote, ccxt_symbol=ccxt_symbol)
    ex = _exchange(testnet=testnet)
    try:
        rows = []
        try:
            rows = ex.fetch_positions([symbol], {"type": "future"})  # type: ignore[attr-defined]
        except Exception:
            rows = []
        if not rows:
            raise ValueError("无法从交易所获取 position（fetch_positions 不可用/失败）")
        pos = rows[0] or {}
        amt = pos.get("contracts")
        if amt is None:
            info = pos.get("info") or {}
            amt = info.get("positionAmt")
        amt_f = float(amt or 0.0)
        if abs(amt_f) <= 1e-12:
            return {"symbol": symbol, "closed": False, "reason": "position already flat"}
        side = "sell" if amt_f > 0 else "buy"
        order = ex.create_order(symbol, "market", side, abs(amt_f), None, {"reduceOnly": True, "type": "future"})
        return {"symbol": symbol, "closed": True, "side": side, "amount": abs(amt_f), "order": order}
    finally:
        try:
            ex.close()
        except Exception:
            pass


def get_position(
    *,
    base: str,
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    """Read-only: fetch current position snapshot for one perp symbol."""
    symbol = _perp_symbol(base, quote, ccxt_symbol=ccxt_symbol)
    if not (settings.binance_api_key and settings.binance_api_secret):
        return {"enabled": False, "symbol": symbol, "position": None, "error": "missing api key/secret"}
    ex = _exchange(testnet=testnet)
    try:
        rows = []
        try:
            rows = ex.fetch_positions([symbol], {"type": "future"})  # type: ignore[attr-defined]
        except Exception:
            rows = []
        pos = (rows[0] if rows else None) or {}

        # Fallback for exchanges/ccxt variants without fetch_positions:
        # Binance USDT-M endpoint: GET /fapi/v2/positionRisk (preferred)
        if not pos:
            fn = getattr(ex, "fapiPrivateV2GetPositionRisk", None) or getattr(ex, "fapiPrivateGetPositionRisk", None)
            if fn:  # ccxt signature endpoints differ by version
                mid = _market_id(ex, symbol)
                raw = fn({"symbol": mid})
                if isinstance(raw, list) and raw:
                    pos = raw[0]
                elif isinstance(raw, dict):
                    pos = raw

        if not pos:
            return {"enabled": True, "symbol": symbol, "position": None, "error": "fetch_positions unavailable/failed"}

        info = pos.get("info") if isinstance(pos, dict) else {}
        amt = None
        if isinstance(pos, dict):
            amt = pos.get("contracts")
            if amt is None:
                amt = pos.get("positionAmt")
            if amt is None and isinstance(info, dict):
                amt = info.get("positionAmt")
        amt_f = float(amt or 0.0)
        side = "flat"
        if abs(amt_f) > 1e-12:
            side = "long" if amt_f > 0 else "short"

        entry = None
        if isinstance(pos, dict):
            entry = pos.get("entryPrice")
            if entry is None and isinstance(info, dict):
                entry = info.get("entryPrice")
        upnl = None
        if isinstance(pos, dict):
            upnl = pos.get("unrealizedPnl")
            if upnl is None and isinstance(info, dict):
                upnl = info.get("unRealizedProfit")
        return {
            "enabled": True,
            "symbol": symbol,
            "position": {
                "side": side,
                "contracts": abs(amt_f),
                "entry_price": float(entry) if entry not in (None, "") else None,
                "unrealized_pnl": float(upnl) if upnl not in (None, "") else None,
            },
        }
    finally:
        try:
            ex.close()
        except Exception:
            pass


def reconcile_protection_from_state(
    *,
    base: str,
    data_dir: str = "data/crypto",
    quote: str = "USDT",
    ccxt_symbol: str | None = None,
    testnet: bool = False,
) -> dict[str, Any]:
    """
    Best-effort reconcile native protection orders using local protection state file.

    - If flat: cancels known SL/TP order ids.
    - If open and stop prices exist: attempts to re-place missing SL/TP.
    """
    _require_not_kill_switched()
    sym = str(base or "").strip().upper()
    symbol = _perp_symbol(sym, quote, ccxt_symbol=ccxt_symbol)
    prot_path = f"{str(data_dir).rstrip('/')}/perp_protection_{sym}.json"
    state = PerpSymbolState.load(prot_path)
    if not state.symbol:
        state.symbol = symbol

    pos_side = str(state.position.side or "flat").lower()
    position_side: PositionSide = "flat" if pos_side not in ("long", "short") else pos_side  # type: ignore[assignment]

    sl = state.sl_order.stop_price
    tp = state.tp_order.stop_price
    amt = float(state.position.amount or 0.0)
    desired: NativeProtectionParams | None = None
    if position_side != "flat" and sl and tp and amt > 0:
        working_type = str(state.sl_order.extra.get("workingType") or "MARK_PRICE")
        desired = NativeProtectionParams(
            symbol=symbol,
            amount=amt,
            sl_stop_price=float(sl),
            tp_stop_price=float(tp),
            working_type="MARK_PRICE" if "MARK" in working_type else "CONTRACT_PRICE",
            sl_client_order_id=str(state.sl_order.client_order_id or ""),
            tp_client_order_id=str(state.tp_order.client_order_id or ""),
        )

    ex = _exchange(testnet=testnet)
    try:
        reconcile_native_protection(ex, state, position_side=position_side, desired=desired)
        state.save(prot_path)
        return {
            "symbol": symbol,
            "position_side": position_side,
            "protection_state_path": prot_path,
            "desired_built": bool(desired),
            "sl_order_id": state.sl_order.exchange_order_id,
            "tp_order_id": state.tp_order.exchange_order_id,
        }
    finally:
        try:
            ex.close()
        except Exception:
            pass

