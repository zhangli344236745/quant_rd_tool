from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TriggerSource = Literal["last", "mark"]

WorkingType = Literal["CONTRACT_PRICE", "MARK_PRICE"]


def trigger_source_to_working_type(source: TriggerSource) -> WorkingType:
    return "CONTRACT_PRICE" if source == "last" else "MARK_PRICE"


@dataclass
class NativeProtectionParams:
    symbol: str
    amount: float
    sl_stop_price: float
    tp_stop_price: float
    working_type: WorkingType
    reduce_only: bool = True
    sl_client_order_id: str = ""
    tp_client_order_id: str = ""


def build_binance_native_protection_orders(p: NativeProtectionParams) -> tuple[dict, dict]:
    """
    Build ccxt order intents for Binance USDT-M futures conditional market orders.

    NOTE: Actual placement is exchange-specific; this returns (sl_intent, tp_intent)
    with required params: stopPrice, workingType, reduceOnly, newClientOrderId.
    """
    sl_intent = {
        "symbol": p.symbol,
        "type": "STOP_MARKET",
        "side": "sell",  # will be corrected by caller based on position direction
        "amount": p.amount,
        "params": {
            "stopPrice": p.sl_stop_price,
            "workingType": p.working_type,
            "reduceOnly": p.reduce_only,
        },
    }
    if p.sl_client_order_id:
        sl_intent["params"]["newClientOrderId"] = p.sl_client_order_id

    tp_intent = {
        "symbol": p.symbol,
        "type": "TAKE_PROFIT_MARKET",
        "side": "sell",
        "amount": p.amount,
        "params": {
            "stopPrice": p.tp_stop_price,
            "workingType": p.working_type,
            "reduceOnly": p.reduce_only,
        },
    }
    if p.tp_client_order_id:
        tp_intent["params"]["newClientOrderId"] = p.tp_client_order_id
    return sl_intent, tp_intent


def place_native_sl_tp(ex, p: NativeProtectionParams, *, position_side: Literal["long", "short"]):
    """
    Place native Binance futures conditional SL/TP (market) via ccxt.

    Returns (sl_order_ref, tp_order_ref) as lightweight dicts.
    """
    sl_intent, tp_intent = build_binance_native_protection_orders(p)
    # For long positions, exits are sells; for short, exits are buys.
    exit_side = "sell" if position_side == "long" else "buy"
    sl_intent["side"] = exit_side
    tp_intent["side"] = exit_side

    sl_order = ex.create_order(
        sl_intent["symbol"],
        sl_intent["type"],
        sl_intent["side"],
        sl_intent["amount"],
        None,
        sl_intent["params"],
    )
    tp_order = ex.create_order(
        tp_intent["symbol"],
        tp_intent["type"],
        tp_intent["side"],
        tp_intent["amount"],
        None,
        tp_intent["params"],
    )

    from quant_rd_tool.perp_state import OrderRef

    sl_ref = OrderRef(
        client_order_id=str(sl_intent["params"].get("newClientOrderId") or ""),
        exchange_order_id=str(sl_order.get("id") or ""),
        order_type=str(sl_intent["type"]),
        side=str(sl_intent["side"]),
        amount=float(sl_intent["amount"]),
        stop_price=float(sl_intent["params"]["stopPrice"]),
        status=str(sl_order.get("status") or ""),
        extra={"workingType": sl_intent["params"].get("workingType")},
    )
    tp_ref = OrderRef(
        client_order_id=str(tp_intent["params"].get("newClientOrderId") or ""),
        exchange_order_id=str(tp_order.get("id") or ""),
        order_type=str(tp_intent["type"]),
        side=str(tp_intent["side"]),
        amount=float(tp_intent["amount"]),
        stop_price=float(tp_intent["params"]["stopPrice"]),
        status=str(tp_order.get("status") or ""),
        extra={"workingType": tp_intent["params"].get("workingType")},
    )
    return sl_ref, tp_ref


def try_place_native_sl_tp(ex, p: NativeProtectionParams, *, position_side: Literal["long", "short"]) -> dict[str, object]:
    """
    Best-effort place native SL/TP. Returns a structured result, allowing partial success.

    This function intentionally performs the two order placements separately so that if
    TP placement fails after SL succeeds, we can return the SL reference.
    """
    from quant_rd_tool.perp_state import OrderRef

    sl_intent, tp_intent = build_binance_native_protection_orders(p)
    exit_side = "sell" if position_side == "long" else "buy"
    sl_intent["side"] = exit_side
    tp_intent["side"] = exit_side

    sl_ref: OrderRef | None = None
    tp_ref: OrderRef | None = None
    try:
        sl_order = ex.create_order(
            sl_intent["symbol"],
            sl_intent["type"],
            sl_intent["side"],
            sl_intent["amount"],
            None,
            sl_intent["params"],
        )
        sl_ref = OrderRef(
            client_order_id=str(sl_intent["params"].get("newClientOrderId") or ""),
            exchange_order_id=str(sl_order.get("id") or ""),
            order_type=str(sl_intent["type"]),
            side=str(sl_intent["side"]),
            amount=float(sl_intent["amount"]),
            stop_price=float(sl_intent["params"]["stopPrice"]),
            status=str(sl_order.get("status") or ""),
            extra={"workingType": sl_intent["params"].get("workingType")},
        )

        tp_order = ex.create_order(
            tp_intent["symbol"],
            tp_intent["type"],
            tp_intent["side"],
            tp_intent["amount"],
            None,
            tp_intent["params"],
        )
        tp_ref = OrderRef(
            client_order_id=str(tp_intent["params"].get("newClientOrderId") or ""),
            exchange_order_id=str(tp_order.get("id") or ""),
            order_type=str(tp_intent["type"]),
            side=str(tp_intent["side"]),
            amount=float(tp_intent["amount"]),
            stop_price=float(tp_intent["params"]["stopPrice"]),
            status=str(tp_order.get("status") or ""),
            extra={"workingType": tp_intent["params"].get("workingType")},
        )
        return {"ok": True, "sl": sl_ref, "tp": tp_ref, "error": ""}
    except Exception as e:
        return {"ok": False, "sl": sl_ref, "tp": tp_ref, "error": str(e)}


def reconcile_native_protection(
    ex,
    state,
    *,
    position_side: Literal["long", "short", "flat"],
    desired: NativeProtectionParams | None,
) -> None:
    """
    Best-effort reconcile for native protection orders.

    - If position is flat: cancel any known SL/TP orders.
    - If position is open: ensure SL & TP exist (best-effort). If one missing, re-place it.
    """
    symbol = state.symbol or (desired.symbol if desired else "")
    if not symbol:
        return
    try:
        open_orders = ex.fetch_open_orders(symbol, None, None, {"type": "future"})
    except Exception:
        open_orders = []
    open_ids = {str(o.get("id") or "") for o in (open_orders or []) if o.get("id")}

    def _cancel(oid: str) -> None:
        if not oid:
            return
        try:
            ex.cancel_order(oid, symbol, {"type": "future"})
        except Exception:
            pass

    if position_side == "flat":
        _cancel(str(state.sl_order.exchange_order_id or ""))
        _cancel(str(state.tp_order.exchange_order_id or ""))
        return

    if desired is None:
        return

    # Replace missing orders individually.
    exit_side = "sell" if position_side == "long" else "buy"

    if state.sl_order.exchange_order_id and str(state.sl_order.exchange_order_id) not in open_ids:
        # Re-place SL
        p = desired
        sl_intent, _ = build_binance_native_protection_orders(p)
        sl_intent["side"] = exit_side
        try:
            o = ex.create_order(
                sl_intent["symbol"],
                sl_intent["type"],
                sl_intent["side"],
                sl_intent["amount"],
                None,
                sl_intent["params"],
            )
            state.sl_order.exchange_order_id = str(o.get("id") or "")
        except Exception:
            pass

    if state.tp_order.exchange_order_id and str(state.tp_order.exchange_order_id) not in open_ids:
        # Re-place TP
        p = desired
        _, tp_intent = build_binance_native_protection_orders(p)
        tp_intent["side"] = exit_side
        try:
            o = ex.create_order(
                tp_intent["symbol"],
                tp_intent["type"],
                tp_intent["side"],
                tp_intent["amount"],
                None,
                tp_intent["params"],
            )
            state.tp_order.exchange_order_id = str(o.get("id") or "")
        except Exception:
            pass

def should_force_close_on_protection_fail(*, fail_streak: int, max_failures: int) -> bool:
    if max_failures <= 0:
        return False
    return int(fail_streak) >= int(max_failures)


SoftTrigger = Literal["sl", "tp"]


def evaluate_soft_sl_tp(
    *,
    position_side: Literal["long", "short"],
    last_price: float,
    sl_price: float,
    tp_price: float,
) -> SoftTrigger | None:
    """
  Check whether last price crossed soft SL/TP levels.

  SL is evaluated before TP when both could apply (conservative).
  """
    if last_price <= 0 or sl_price <= 0 or tp_price <= 0:
        return None
    if position_side == "long":
        if last_price <= sl_price:
            return "sl"
        if last_price >= tp_price:
            return "tp"
    else:
        if last_price >= sl_price:
            return "sl"
        if last_price <= tp_price:
            return "tp"
    return None


def apply_protection_policy_to_state(
    state,
    policy: dict[str, object],
    *,
    sl_price: float | None = None,
    tp_price: float | None = None,
    position_side: str = "",
) -> None:
    state.protection_fail_streak = int(policy.get("fail_streak") or 0)
    soft = bool(policy.get("soft_active"))
    state.soft_protection_active = soft
    if soft and sl_price is not None and tp_price is not None and position_side in ("long", "short"):
        state.soft_sl_price = float(sl_price)
        state.soft_tp_price = float(tp_price)
        state.soft_position_side = position_side
    elif not soft:
        state.soft_sl_price = None
        state.soft_tp_price = None
        state.soft_position_side = ""


def build_native_protection_params(
    *,
    symbol: str,
    amount: float,
    position_side: Literal["long", "short"],
    ref_price: float,
    sl_pct: float,
    tp_pct: float,
    trigger_source: TriggerSource,
    client_order_id_prefix: str,
    atr: float | None = None,
    sl_atr: float | None = None,
    tp_atr: float | None = None,
) -> NativeProtectionParams:
    from quant_rd_tool.perp_risk import compute_sl_tp_prices, compute_sl_tp_prices_atr

    if atr is not None and atr > 0 and sl_atr is not None and tp_atr is not None:
        sl, tp = compute_sl_tp_prices_atr(
            side=position_side,
            ref_price=ref_price,
            atr=atr,
            sl_atr=float(sl_atr),
            tp_atr=float(tp_atr),
        )
    else:
        sl, tp = compute_sl_tp_prices(
            side=position_side,
            ref_price=ref_price,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
        )
    wtype = trigger_source_to_working_type(trigger_source)
    base = client_order_id_prefix[:32]
    return NativeProtectionParams(
        symbol=symbol,
        amount=amount,
        sl_stop_price=sl,
        tp_stop_price=tp,
        working_type=wtype,
        sl_client_order_id=f"{base}_sl"[:36],
        tp_client_order_id=f"{base}_tp"[:36],
    )


def decide_protection_policy(
    *,
    current_fail_streak: int,
    native_ok: bool,
    max_failures: int,
) -> dict[str, object]:
    """
    Strategy C:
    - native ok: reset streak, soft protection off
    - native fail: enable soft protection, increment streak
    - if streak reaches max_failures: force close
    """
    if native_ok:
        return {"fail_streak": 0, "soft_active": False, "force_close": False}
    streak = int(current_fail_streak) + 1
    force_close = should_force_close_on_protection_fail(fail_streak=streak, max_failures=max_failures)
    return {"fail_streak": streak, "soft_active": True, "force_close": force_close}

