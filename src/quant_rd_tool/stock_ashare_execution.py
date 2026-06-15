"""A-share execution rules: T+1, lot size, fees, limit up/down (institutional v1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

DEFAULT_EXECUTION_RULES: dict[str, Any] = {
    "market": "ashare",
    "t_plus_one": True,
    "lot_size": 100,
    "limit_model": "prev_close_pct",
}


@dataclass
class AShareFeeSchedule:
    commission_rate: float = 0.00025
    min_commission_cny: float = 5.0
    stamp_duty_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_bps: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AShareBoardRules:
    main_limit_pct: float = 0.10
    growth_limit_pct: float = 0.20
    lot_size: int = 100
    t_plus_one: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionStats:
    total_commission: float = 0.0
    total_stamp_duty: float = 0.0
    total_transfer_fee: float = 0.0
    total_slippage: float = 0.0
    blocked_limit_up: int = 0
    blocked_limit_down: int = 0
    blocked_t_plus_one: int = 0
    blocked_lot_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def round_price(price: float) -> float:
    return round(float(price), 2)


def infer_limit_pct(code: str, *, rules: AShareBoardRules | None = None) -> float:
    rules = rules or AShareBoardRules()
    c = str(code).upper()
    if c.startswith("SH688") or c.startswith("SZ300") or c.startswith("SZ301"):
        return rules.growth_limit_pct
    return rules.main_limit_pct


def is_shanghai(code: str) -> bool:
    c = str(code).upper()
    return c.startswith("SH") or (c.isdigit() and c.startswith("6"))


def limit_prices(prev_close: float, limit_pct: float) -> tuple[float, float]:
    if prev_close <= 0:
        return 0.0, 0.0
    up = round_price(prev_close * (1 + limit_pct))
    down = round_price(prev_close * (1 - limit_pct))
    return up, down


def is_limit_up(close: float, prev_close: float, limit_pct: float) -> bool:
    if prev_close <= 0:
        return False
    up, _ = limit_prices(prev_close, limit_pct)
    return float(close) >= up - 0.005


def is_limit_down(close: float, prev_close: float, limit_pct: float) -> bool:
    if prev_close <= 0:
        return False
    _, down = limit_prices(prev_close, limit_pct)
    return float(close) <= down + 0.005


def round_to_lot(shares: float, lot_size: int = 100) -> int:
    if shares <= 0 or lot_size <= 0:
        return 0
    return int(shares // lot_size) * lot_size


def calc_trade_fees(
    *,
    side: str,
    notional: float,
    code: str,
    schedule: AShareFeeSchedule,
) -> tuple[float, float, float]:
    notional = abs(float(notional))
    commission = max(notional * schedule.commission_rate, schedule.min_commission_cny)
    stamp = notional * schedule.stamp_duty_rate if side == "sell" else 0.0
    transfer = notional * schedule.transfer_fee_rate if is_shanghai(code) else 0.0
    return commission, stamp, transfer


def execution_rules_payload(
    *,
    fees: AShareFeeSchedule | None = None,
    board: AShareBoardRules | None = None,
) -> dict[str, Any]:
    fees = fees or AShareFeeSchedule()
    board = board or AShareBoardRules()
    return {
        **DEFAULT_EXECUTION_RULES,
        "fee_schedule": fees.to_dict(),
        "board_rules": board.to_dict(),
    }


def run_topk_backtest_ashare(
    scores: pd.DataFrame,
    close: pd.DataFrame,
    *,
    topk: int,
    initial_cash: float,
    fees: AShareFeeSchedule | None = None,
    board: AShareBoardRules | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]], ExecutionStats]:
    """Daily Top-K rebalance with A-share constraints."""
    fees = fees or AShareFeeSchedule()
    board = board or AShareBoardRules()
    stats = ExecutionStats()
    trades: list[dict[str, Any]] = []

    scores = scores.shift(1)
    prev_close = close.shift(1)
    dates = scores.dropna(how="all").index.intersection(close.index)
    cash = float(initial_cash)
    holdings: dict[str, int] = {}
    bought_today: dict[str, int] = {}

    report_rows: list[dict[str, Any]] = []
    weight_rows: list[dict[str, Any]] = []

    slippage_rate = fees.slippage_bps / 10_000.0

    for dt in dates:
        bought_today = {}
        row = scores.loc[dt].dropna()
        if row.empty:
            continue
        targets = row.nlargest(min(topk, len(row))).index.tolist()
        prices = close.loc[dt, targets].astype(float)
        prev = prev_close.loc[dt]

        port_value = cash + sum(holdings.get(t, 0) * float(close.loc[dt, t]) for t in holdings)
        if port_value <= 0:
            continue

        target_w = 1.0 / len(targets)

        for t in list(holdings):
            if t in targets:
                continue
            sellable = holdings.get(t, 0) - bought_today.get(t, 0)
            if sellable <= 0:
                if holdings.get(t, 0) > 0:
                    stats.blocked_t_plus_one += 1
                continue
            px = float(close.loc[dt, t])
            pc = float(prev.get(t, px))
            lp = infer_limit_pct(t, rules=board)
            if is_limit_down(px, pc, lp):
                stats.blocked_limit_down += 1
                continue
            fill = px * (1.0 - slippage_rate)
            notional = sellable * fill
            comm, stamp, xfer = calc_trade_fees(side="sell", notional=notional, code=t, schedule=fees)
            slip = notional * slippage_rate
            proceeds = notional - comm - stamp - xfer - slip
            cash += proceeds
            stats.total_commission += comm
            stats.total_stamp_duty += stamp
            stats.total_transfer_fee += xfer
            stats.total_slippage += slip
            holdings[t] = holdings.get(t, 0) - sellable
            if holdings[t] <= 0:
                holdings.pop(t, None)
            trades.append(
                {
                    "date": str(dt.date()) if hasattr(dt, "date") else str(dt),
                    "code": t,
                    "side": "sell",
                    "shares": sellable,
                    "price": round(fill, 4),
                    "commission": round(comm, 2),
                    "stamp_duty": round(stamp, 2),
                }
            )

        for t in targets:
            port_value = cash + sum(holdings.get(x, 0) * float(close.loc[dt, x]) for x in holdings)
            px = float(prices[t])
            if px <= 0:
                continue
            pc = float(prev.get(t, px))
            lp = infer_limit_pct(t, rules=board)
            if is_limit_up(px, pc, lp):
                stats.blocked_limit_up += 1
                continue
            desired_value = port_value * target_w
            desired_shares = round_to_lot(desired_value / px, board.lot_size)
            current = holdings.get(t, 0)
            delta = desired_shares - current
            if delta == 0:
                continue
            if delta < 0:
                sellable = min(-delta, current - bought_today.get(t, 0))
                if sellable <= 0:
                    stats.blocked_t_plus_one += 1
                    continue
                if is_limit_down(px, pc, lp):
                    stats.blocked_limit_down += 1
                    continue
                fill = px * (1.0 - slippage_rate)
                notional = sellable * fill
                comm, stamp, xfer = calc_trade_fees(side="sell", notional=notional, code=t, schedule=fees)
                slip = notional * slippage_rate
                cash += notional - comm - stamp - xfer - slip
                stats.total_commission += comm
                stats.total_stamp_duty += stamp
                stats.total_transfer_fee += xfer
                stats.total_slippage += slip
                holdings[t] = current - sellable
                if holdings[t] <= 0:
                    holdings.pop(t, None)
                trades.append(
                    {
                        "date": str(dt.date()) if hasattr(dt, "date") else str(dt),
                        "code": t,
                        "side": "sell",
                        "shares": sellable,
                        "price": round(fill, 4),
                    }
                )
                continue

            fill = px * (1.0 + slippage_rate)
            buy_shares = round_to_lot(delta, board.lot_size)
            if buy_shares <= 0:
                stats.blocked_lot_size += 1
                continue
            notional = buy_shares * fill
            comm, stamp, xfer = calc_trade_fees(side="buy", notional=notional, code=t, schedule=fees)
            slip = notional * slippage_rate
            total_cost = notional + comm + stamp + xfer + slip
            if total_cost > cash:
                affordable = round_to_lot((cash - comm) / fill, board.lot_size)
                if affordable <= 0:
                    continue
                buy_shares = affordable
                notional = buy_shares * fill
                comm, stamp, xfer = calc_trade_fees(side="buy", notional=notional, code=t, schedule=fees)
                slip = notional * slippage_rate
                total_cost = notional + comm + stamp + xfer + slip
            cash -= total_cost
            stats.total_commission += comm
            stats.total_stamp_duty += stamp
            stats.total_transfer_fee += xfer
            stats.total_slippage += slip
            holdings[t] = holdings.get(t, 0) + buy_shares
            bought_today[t] = bought_today.get(t, 0) + buy_shares
            trades.append(
                {
                    "date": str(dt.date()) if hasattr(dt, "date") else str(dt),
                    "code": t,
                    "side": "buy",
                    "shares": buy_shares,
                    "price": round(fill, 4),
                    "commission": round(comm, 2),
                }
            )

        end_value = cash + sum(holdings.get(t, 0) * float(close.loc[dt, t]) for t in holdings)
        prev_value = report_rows[-1]["portfolio_value"] if report_rows else initial_cash
        daily_ret = end_value / prev_value - 1 if prev_value else 0.0
        day_cost = (
            stats.total_commission
            + stats.total_stamp_duty
            + stats.total_transfer_fee
            + stats.total_slippage
        )
        day_cost_prev = day_cost - (
            0 if not report_rows else report_rows[-1].get("_cum_cost", 0.0)
        )
        report_rows.append(
            {
                "date": dt,
                "return": daily_ret,
                "cost": day_cost_prev / prev_value if prev_value else 0.0,
                "portfolio_value": end_value,
                "_cum_cost": day_cost,
            }
        )
        weight_rows.append(
            {
                "date": dt,
                **{
                    t: holdings.get(t, 0) * float(close.loc[dt, t]) / end_value
                    for t in targets
                    if t in holdings
                },
            }
        )

    report = pd.DataFrame(report_rows).set_index("date") if report_rows else pd.DataFrame()
    if not report.empty and "_cum_cost" in report.columns:
        report = report.drop(columns=["_cum_cost"])
    weights = pd.DataFrame(weight_rows).set_index("date") if weight_rows else pd.DataFrame()
    return report, weights, trades, stats
