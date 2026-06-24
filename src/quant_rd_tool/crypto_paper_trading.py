"""Paper-trading engine for crypto bots.

Simulates market fills (with fees + slippage) from the *same* signal/action the
live bot would emit, persists an equity curve and trade ledger to disk, and
computes performance metrics (net value, win rate, drawdown). This lets a bot
strategy be validated forward without risking capital, and gives every bot a
trackable P&L regardless of dry-run vs live.
"""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Action = Literal["buy", "sell", "hold"]

DEFAULT_FEE_PCT = 0.001
DEFAULT_SLIPPAGE_PCT = 0.0005


@dataclass
class PaperPosition:
    base_amount: float = 0.0
    entry_price: float = 0.0
    sl_price: float | None = None
    tp_price: float | None = None


@dataclass
class PaperAccount:
    symbol: str = "BTC"
    quote: str = "USDT"
    initial_cash: float = 10_000.0
    cash: float = 10_000.0
    position: PaperPosition = field(default_factory=PaperPosition)
    fee_pct: float = DEFAULT_FEE_PCT
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def equity(self, price: float) -> float:
        return self.cash + self.position.base_amount * float(price)

    @staticmethod
    def load(path: str | Path, *, symbol: str, quote: str, initial_cash: float) -> PaperAccount:
        p = Path(path)
        if not p.exists():
            now = now_iso()
            return PaperAccount(
                symbol=symbol,
                quote=quote,
                initial_cash=initial_cash,
                cash=initial_cash,
                created_at=now,
                updated_at=now,
            )
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
        pos = data.get("position") or {}
        return PaperAccount(
            symbol=data.get("symbol", symbol),
            quote=data.get("quote", quote),
            initial_cash=float(data.get("initial_cash", initial_cash)),
            cash=float(data.get("cash", initial_cash)),
            position=PaperPosition(
                base_amount=float(pos.get("base_amount", 0.0)),
                entry_price=float(pos.get("entry_price", 0.0)),
                sl_price=pos.get("sl_price"),
                tp_price=pos.get("tp_price"),
            ),
            fee_pct=float(data.get("fee_pct", DEFAULT_FEE_PCT)),
            slippage_pct=float(data.get("slippage_pct", DEFAULT_SLIPPAGE_PCT)),
            realized_pnl=float(data.get("realized_pnl", 0.0)),
            total_fees=float(data.get("total_fees", 0.0)),
            trades=list(data.get("trades") or []),
            equity_curve=list(data.get("equity_curve") or []),
            created_at=data.get("created_at") or now_iso(),
            updated_at=data.get("updated_at") or now_iso(),
        )

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        p.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")


def _record_trade(
    account: PaperAccount,
    *,
    side: str,
    price: float,
    base_amount: float,
    fee: float,
    ts: str,
    reason: str,
    realized: float | None = None,
) -> dict[str, Any]:
    trade = {
        "ts": ts,
        "side": side,
        "price": round(float(price), 8),
        "base_amount": round(float(base_amount), 10),
        "quote_amount": round(float(price) * float(base_amount), 6),
        "fee": round(float(fee), 6),
        "reason": reason,
        "realized_pnl": round(float(realized), 6) if realized is not None else None,
    }
    account.trades.append(trade)
    return trade


def apply_action(
    account: PaperAccount,
    *,
    action: Action,
    price: float,
    ts: str | None = None,
    target_quote_amount: float | None = None,
    sl_price: float | None = None,
    tp_price: float | None = None,
    reason: str = "signal",
) -> dict[str, Any]:
    """Apply a discrete action at ``price`` to the paper account.

    - ``buy``  : open/add a long with ``target_quote_amount`` (defaults to all cash).
    - ``sell`` : flatten the long position.
    - ``hold`` : no fill; only records equity.
    Fills include slippage (against us) and a percentage fee.
    """
    if price <= 0:
        raise ValueError("price must be positive")
    ts = ts or now_iso()
    fill_buy = price * (1.0 + account.slippage_pct)
    fill_sell = price * (1.0 - account.slippage_pct)
    order: dict[str, Any] | None = None

    if action == "buy" and account.position.base_amount <= 0:
        budget = (
            account.cash if target_quote_amount is None else min(target_quote_amount, account.cash)
        )
        if budget > 0:
            base_amount = budget / (fill_buy * (1.0 + account.fee_pct))
            fee = base_amount * fill_buy * account.fee_pct
            account.cash -= base_amount * fill_buy + fee
            account.total_fees += fee
            account.position = PaperPosition(
                base_amount=base_amount,
                entry_price=fill_buy,
                sl_price=sl_price,
                tp_price=tp_price,
            )
            order = _record_trade(
                account,
                side="buy",
                price=fill_buy,
                base_amount=base_amount,
                fee=fee,
                ts=ts,
                reason=reason,
            )
    elif action == "sell" and account.position.base_amount > 0:
        base_amount = account.position.base_amount
        proceeds = base_amount * fill_sell
        fee = proceeds * account.fee_pct
        cost = base_amount * account.position.entry_price
        realized = proceeds - fee - cost
        account.cash += proceeds - fee
        account.total_fees += fee
        account.realized_pnl += realized
        order = _record_trade(
            account,
            side="sell",
            price=fill_sell,
            base_amount=base_amount,
            fee=fee,
            ts=ts,
            reason=reason,
            realized=realized,
        )
        account.position = PaperPosition()

    equity = round(account.equity(price), 6)
    account.equity_curve.append({"ts": ts, "price": round(float(price), 8), "equity": equity})
    account.updated_at = ts
    return {"order": order, "equity": equity, "position": asdict(account.position)}


def check_soft_protection(
    account: PaperAccount, *, price: float, ts: str | None = None
) -> dict[str, Any] | None:
    """Flatten the paper long if price crossed the stored SL/TP."""
    pos = account.position
    if pos.base_amount <= 0:
        return None
    hit: str | None = None
    if pos.sl_price is not None and price <= pos.sl_price:
        hit = "stop_loss"
    elif pos.tp_price is not None and price >= pos.tp_price:
        hit = "take_profit"
    if not hit:
        return None
    out = apply_action(account, action="sell", price=price, ts=ts, reason=hit)
    return {"triggered": hit, **out}


def compute_performance(account: PaperAccount) -> dict[str, Any]:
    curve = account.equity_curve
    last_price = float(curve[-1]["price"]) if curve else account.position.entry_price
    equity = account.equity(last_price) if last_price else account.cash
    total_return = (equity / account.initial_cash - 1.0) if account.initial_cash > 0 else 0.0

    sells = [t for t in account.trades if t["side"] == "sell" and t.get("realized_pnl") is not None]
    wins = [t for t in sells if float(t["realized_pnl"]) > 0]
    win_rate = (len(wins) / len(sells)) if sells else None
    gross_win = sum(float(t["realized_pnl"]) for t in wins)
    gross_loss = -sum(float(t["realized_pnl"]) for t in sells if float(t["realized_pnl"]) < 0)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None

    max_dd = 0.0
    peak = -math.inf
    for row in curve:
        eq = float(row["equity"])
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)

    return {
        "initial_cash": round(account.initial_cash, 2),
        "equity": round(equity, 2),
        "cash": round(account.cash, 2),
        "position_base": round(account.position.base_amount, 10),
        "realized_pnl": round(account.realized_pnl, 4),
        "unrealized_pnl": round(
            account.position.base_amount * (last_price - account.position.entry_price), 4
        )
        if account.position.base_amount > 0
        else 0.0,
        "total_return": round(total_return, 6),
        "total_fees": round(account.total_fees, 4),
        "trade_count": len(account.trades),
        "closed_trades": len(sells),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "max_drawdown": round(max_dd, 6),
        "last_price": round(last_price, 8) if last_price else None,
    }
