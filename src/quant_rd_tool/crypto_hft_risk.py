"""Risk limits and PnL tracking for crypto market-making bots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from quant_rd_tool.crypto_hft_strategies import Quote

Side = Literal["buy", "sell"]

_PNL_SNAPSHOT_CAP = 500


@dataclass(frozen=True)
class RiskLimits:
    max_session_loss_usdt: float = 0.0
    max_inventory_usdt: float = 500.0
    max_daily_loss_usdt: float = 0.0


@dataclass(frozen=True)
class RiskDecision:
    halted: bool
    reason: str
    allow_buy: bool
    allow_sell: bool


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _today_utc() -> str:
    return date.today().isoformat()


def default_pnl_block() -> dict[str, Any]:
    return {
        "realized_usdt": 0.0,
        "unrealized_usdt": 0.0,
        "total_usdt": 0.0,
        "session_usdt": 0.0,
        "daily_usdt": 0.0,
        "total_fees_usdt": 0.0,
        "fill_count": 0,
    }


def default_risk_block() -> dict[str, Any]:
    return {
        "halted": False,
        "halt_reason": None,
        "allow_buy": True,
        "allow_sell": True,
    }


def enrich_default_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("pnl", default_pnl_block())
    state.setdefault("risk", default_risk_block())
    state.setdefault("session_start_pnl_usdt", 0.0)
    state.setdefault("daily_date", None)
    state.setdefault("daily_start_pnl_usdt", 0.0)
    state.setdefault("last_fill_ts_ms", 0)
    state.setdefault("pnl_snapshots", [])
    state.setdefault("avg_entry_price", 0.0)
    state.setdefault("realized_pnl_usdt", 0.0)
    return state


def resolve_max_inventory_usdt(
    *,
    bot_max_inventory_usdt: float,
    strategy_params: dict[str, Any] | None,
) -> float:
    if bot_max_inventory_usdt > 0:
        return float(bot_max_inventory_usdt)
    return float((strategy_params or {}).get("max_inventory_usdt") or 500.0)


def begin_risk_session(state: dict[str, Any]) -> None:
    enrich_default_state(state)
    total = float((state.get("pnl") or {}).get("total_usdt") or 0)
    state["session_start_pnl_usdt"] = total
    state["session_started_at"] = _iso_now()
    risk = dict(state.get("risk") or default_risk_block())
    risk["halted"] = False
    risk["halt_reason"] = None
    risk["allow_buy"] = True
    risk["allow_sell"] = True
    state["risk"] = risk


def _sync_pnl_totals(state: dict[str, Any]) -> dict[str, Any]:
    enrich_default_state(state)
    pnl = dict(state["pnl"])
    realized = float(state.get("realized_pnl_usdt") or pnl.get("realized_usdt") or 0)
    unrealized = float(pnl.get("unrealized_usdt") or 0)
    total = realized + unrealized
    session_start = float(state.get("session_start_pnl_usdt") or 0)
    today = _today_utc()
    daily_date = state.get("daily_date")
    if daily_date != today:
        state["daily_date"] = today
        state["daily_start_pnl_usdt"] = total
    daily_start = float(state.get("daily_start_pnl_usdt") or total)
    pnl.update(
        {
            "realized_usdt": round(realized, 6),
            "unrealized_usdt": round(unrealized, 6),
            "total_usdt": round(total, 6),
            "session_usdt": round(total - session_start, 6),
            "daily_usdt": round(total - daily_start, 6),
        }
    )
    state["pnl"] = pnl
    state["realized_pnl_usdt"] = realized
    return pnl


def update_mtm_from_inventory(
    state: dict[str, Any],
    *,
    inventory_base: float,
    mark_price: float,
    unrealized_pnl: float | None = None,
    avg_entry_price: float | None = None,
) -> dict[str, Any]:
    enrich_default_state(state)
    if avg_entry_price is not None and avg_entry_price > 0:
        state["avg_entry_price"] = float(avg_entry_price)
    avg = float(state.get("avg_entry_price") or 0)
    if unrealized_pnl is not None:
        upnl = float(unrealized_pnl)
    elif avg > 0 and inventory_base != 0:
        upnl = float(inventory_base) * (float(mark_price) - avg)
    else:
        upnl = 0.0
    pnl = dict(state["pnl"])
    pnl["unrealized_usdt"] = round(upnl, 6)
    state["pnl"] = pnl
    state["inventory_base"] = float(inventory_base)
    return _sync_pnl_totals(state)


def apply_fill(
    state: dict[str, Any],
    *,
    side: Side,
    price: float,
    amount: float,
    fee_usdt: float = 0.0,
) -> dict[str, Any]:
    enrich_default_state(state)
    if amount <= 0 or price <= 0:
        return _sync_pnl_totals(state)

    inv = float(state.get("inventory_base") or 0)
    avg = float(state.get("avg_entry_price") or 0)
    realized_delta = 0.0
    px = float(price)
    qty = float(amount)
    fee = max(float(fee_usdt), 0.0)

    if side == "buy":
        if inv >= 0:
            new_inv = inv + qty
            avg = (inv * avg + qty * px) / new_inv if new_inv > 0 else px
        else:
            cover = min(qty, abs(inv))
            if cover > 0:
                realized_delta += cover * (avg - px)
            new_inv = inv + qty
            if new_inv > 0:
                avg = px
        inv = new_inv
    else:
        if inv > 0:
            sold = min(qty, inv)
            if sold > 0:
                realized_delta += sold * (px - avg)
            inv -= qty
            if inv <= 0:
                avg = px if inv < 0 else 0.0
        else:
            new_short = abs(inv) + qty
            avg = (abs(inv) * avg + qty * px) / new_short if new_short > 0 else px
            inv -= qty

    pnl = dict(state["pnl"])
    realized = float(state.get("realized_pnl_usdt") or 0) + realized_delta - fee
    pnl["total_fees_usdt"] = round(float(pnl.get("total_fees_usdt") or 0) + fee, 6)
    pnl["fill_count"] = int(pnl.get("fill_count") or 0) + 1
    state["inventory_base"] = inv
    state["avg_entry_price"] = avg if inv != 0 else 0.0
    state["realized_pnl_usdt"] = realized
    state["pnl"] = pnl
    return _sync_pnl_totals(state)


def process_fills(
    state: dict[str, Any],
    fills: list[dict[str, Any]],
    *,
    maker_fee_bps: float = 2.0,
) -> list[dict[str, Any]]:
    enrich_default_state(state)
    last_ms = int(state.get("last_fill_ts_ms") or 0)
    new_rows: list[dict[str, Any]] = []
    max_ts = last_ms
    for row in sorted(fills, key=lambda r: int(r.get("timestamp") or 0)):
        ts = int(row.get("timestamp") or 0)
        if ts <= last_ms:
            continue
        side = str(row.get("side") or "").lower()
        if side not in ("buy", "sell"):
            continue
        price = float(row.get("price") or 0)
        amount = float(row.get("amount") or 0)
        raw_fee = row.get("fee")
        if isinstance(raw_fee, dict):
            fee_usdt = float(raw_fee.get("cost") or 0)
        else:
            fee_usdt = float(raw_fee or 0)
        if fee_usdt <= 0 and price > 0 and amount > 0:
            fee_usdt = price * amount * float(maker_fee_bps) / 10_000.0
        apply_fill(state, side=side, price=price, amount=amount, fee_usdt=fee_usdt)
        max_ts = max(max_ts, ts)
        new_rows.append(row)
    if max_ts > last_ms:
        state["last_fill_ts_ms"] = max_ts
    return new_rows


def record_pnl_snapshot(state: dict[str, Any], *, mark_price: float | None) -> None:
    enrich_default_state(state)
    pnl = _sync_pnl_totals(state)
    snaps: list[dict[str, Any]] = list(state.get("pnl_snapshots") or [])
    snaps.append(
        {
            "ts": _iso_now(),
            "total_usdt": pnl.get("total_usdt"),
            "session_usdt": pnl.get("session_usdt"),
            "mid": mark_price,
        }
    )
    if len(snaps) > _PNL_SNAPSHOT_CAP:
        snaps = snaps[-_PNL_SNAPSHOT_CAP:]
    state["pnl_snapshots"] = snaps


def evaluate_risk(
    state: dict[str, Any],
    limits: RiskLimits,
    *,
    inventory_usdt: float,
) -> RiskDecision:
    enrich_default_state(state)
    pnl = _sync_pnl_totals(state)
    session_pnl = float(pnl.get("session_usdt") or 0)
    daily_pnl = float(pnl.get("daily_usdt") or 0)
    inv = float(inventory_usdt)
    max_inv = float(limits.max_inventory_usdt)

    allow_buy = True
    allow_sell = True
    if max_inv > 0:
        if inv >= max_inv:
            allow_buy = False
        if inv <= -max_inv:
            allow_sell = False

    reason = ""
    halted = False
    if limits.max_session_loss_usdt > 0 and session_pnl <= -limits.max_session_loss_usdt:
        halted = True
        reason = f"session_loss {session_pnl:.2f} <= -{limits.max_session_loss_usdt:.2f}"
    elif limits.max_daily_loss_usdt > 0 and daily_pnl <= -limits.max_daily_loss_usdt:
        halted = True
        reason = f"daily_loss {daily_pnl:.2f} <= -{limits.max_daily_loss_usdt:.2f}"

    if halted:
        allow_buy = False
        allow_sell = False

    risk = dict(state.get("risk") or default_risk_block())
    risk.update(
        {
            "halted": halted,
            "halt_reason": reason or None,
            "allow_buy": allow_buy,
            "allow_sell": allow_sell,
        }
    )
    state["risk"] = risk
    if halted:
        state["status"] = "risk_halted"
    return RiskDecision(
        halted=halted,
        reason=reason,
        allow_buy=allow_buy,
        allow_sell=allow_sell,
    )


def filter_quotes_by_risk(quotes: list[Quote], decision: RiskDecision) -> list[Quote]:
    if decision.halted:
        return []
    out: list[Quote] = []
    for q in quotes:
        if q.side == "buy" and not decision.allow_buy:
            continue
        if q.side == "sell" and not decision.allow_sell:
            continue
        out.append(q)
    return out


def risk_summary(state: dict[str, Any]) -> dict[str, Any]:
    enrich_default_state(state)
    pnl = _sync_pnl_totals(state)
    risk = dict(state.get("risk") or default_risk_block())
    return {"pnl": pnl, "risk": risk}


def refresh_risk_state(
    state: dict[str, Any],
    *,
    inventory: dict[str, float],
    mid: float | None,
    limits: RiskLimits,
    fills: list[dict[str, Any]],
    maker_fee_bps: float,
) -> tuple[RiskDecision, list[dict[str, Any]]]:
    new_fills = process_fills(state, fills, maker_fee_bps=maker_fee_bps)
    mark = float(inventory.get("mark_price") or mid or 0)
    update_mtm_from_inventory(
        state,
        inventory_base=float(inventory.get("inventory_base") or 0),
        mark_price=mark,
        unrealized_pnl=inventory.get("unrealized_pnl"),
        avg_entry_price=inventory.get("avg_entry_price"),
    )
    record_pnl_snapshot(state, mark_price=mid)
    decision = evaluate_risk(
        state,
        limits,
        inventory_usdt=float(inventory.get("inventory_usdt") or 0),
    )
    return decision, new_fills
