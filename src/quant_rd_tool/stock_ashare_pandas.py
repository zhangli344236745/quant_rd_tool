"""Pandas bar backtest with A-share execution rules."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

import pandas as pd

from quant_rd_tool.crypto_zipline_pandas import _bar_time, _equity_point, _metrics
from quant_rd_tool.stock_ashare_execution import (
    AShareBoardRules,
    AShareFeeSchedule,
    ExecutionStats,
    calc_trade_fees,
    execution_rules_payload,
    infer_limit_pct,
    is_limit_down,
    is_limit_up,
    round_to_lot,
)

_ASHARE_CTX: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "ashare_backtest_ctx", default=None
)


def get_ashare_ctx() -> dict[str, Any] | None:
    return _ASHARE_CTX.get()


@contextmanager
def ashare_backtest_context(
    *,
    symbol: str = "",
    fees: AShareFeeSchedule | None = None,
    board: AShareBoardRules | None = None,
    use_ashare: bool = True,
) -> Iterator[None]:
    if not use_ashare:
        yield
        return
    token = _ASHARE_CTX.set(
        {
            "symbol": symbol,
            "fees": fees or AShareFeeSchedule(),
            "board": board or AShareBoardRules(),
        }
    )
    try:
        yield
    finally:
        _ASHARE_CTX.reset(token)


def run_ashare_bar_backtest(
    df: pd.DataFrame,
    *,
    capital_base: float,
    warmup: int,
    target_col: str = "target",
    symbol: str = "",
    fees: AShareFeeSchedule | None = None,
    board: AShareBoardRules | None = None,
    bars_per_year: int | None = 252,
) -> dict[str, Any]:
    if df.empty:
        raise ValueError("empty dataframe")

    ctx = get_ashare_ctx() or {}
    fees = fees or ctx.get("fees") or AShareFeeSchedule()
    board = board or ctx.get("board") or AShareBoardRules()
    symbol = symbol or str(ctx.get("symbol") or "")

    stats = ExecutionStats()
    slippage_rate = fees.slippage_bps / 10_000.0
    limit_pct = infer_limit_pct(symbol, rules=board)

    work = df.reset_index(drop=True)
    cash = float(capital_base)
    shares = 0
    bought_today = 0
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    prev_target = 0.0
    round_trips: list[float] = []
    open_cost_basis = 0.0
    prev_date: Any = None

    for i, row in work.iterrows():
        price = float(row["close"])
        prev_close = float(work.iloc[i - 1]["close"]) if i > 0 else price
        bar_date = row.get("date") if "date" in row.index else i

        if prev_date is not None and bar_date != prev_date:
            bought_today = 0
        prev_date = bar_date

        if i < warmup or pd.isna(row.get(target_col)):
            equity = cash + shares * price
            equity_curve.append(_equity_point(row, equity, target=prev_target))
            continue

        target = max(0.0, min(1.0, float(row[target_col])))
        equity = cash + shares * price
        desired_shares = round_to_lot((equity * target) / price if price > 0 else 0, board.lot_size)
        delta = desired_shares - shares

        if delta < 0:
            sellable = min(-delta, shares - bought_today)
            if sellable <= 0 and -delta > 0:
                stats.blocked_t_plus_one += 1
            elif sellable > 0:
                if is_limit_down(price, prev_close, limit_pct):
                    stats.blocked_limit_down += 1
                else:
                    fill = price * (1.0 - slippage_rate)
                    notional = sellable * fill
                    comm, stamp, xfer = calc_trade_fees(
                        side="sell", notional=notional, code=symbol, schedule=fees
                    )
                    slip = notional * slippage_rate
                    proceeds = notional - comm - stamp - xfer - slip
                    cash += proceeds
                    stats.total_commission += comm
                    stats.total_stamp_duty += stamp
                    stats.total_transfer_fee += xfer
                    stats.total_slippage += slip
                    sold_fraction = sellable / shares if shares > 0 else 1.0
                    basis = open_cost_basis * sold_fraction
                    round_trips.append(proceeds - basis)
                    open_cost_basis = max(0.0, open_cost_basis - basis)
                    shares -= sellable
                    trades.append(
                        {
                            "time": _bar_time(row),
                            "side": "sell",
                            "price": round(fill, 4),
                            "shares": sellable,
                            "fee": round(comm + stamp + xfer, 2),
                        }
                    )

        elif delta > 0:
            if is_limit_up(price, prev_close, limit_pct):
                stats.blocked_limit_up += 1
            else:
                fill = price * (1.0 + slippage_rate)
                buy_shares = round_to_lot(delta, board.lot_size)
                if buy_shares <= 0:
                    stats.blocked_lot_size += 1
                else:
                    notional = buy_shares * fill
                    comm, stamp, xfer = calc_trade_fees(
                        side="buy", notional=notional, code=symbol, schedule=fees
                    )
                    slip = notional * slippage_rate
                    total = notional + comm + stamp + xfer + slip
                    if total > cash:
                        buy_shares = round_to_lot(
                            max(0, (cash - fees.min_commission_cny) / fill), board.lot_size
                        )
                        if buy_shares <= 0:
                            buy_shares = 0
                        else:
                            notional = buy_shares * fill
                            comm, stamp, xfer = calc_trade_fees(
                                side="buy", notional=notional, code=symbol, schedule=fees
                            )
                            slip = notional * slippage_rate
                            total = notional + comm + stamp + xfer + slip
                    if buy_shares > 0 and total <= cash:
                        cash -= total
                        stats.total_commission += comm
                        stats.total_stamp_duty += stamp
                        stats.total_transfer_fee += xfer
                        stats.total_slippage += slip
                        open_cost_basis += notional + comm + stamp + xfer
                        shares += buy_shares
                        bought_today += buy_shares
                        trades.append(
                            {
                                "time": _bar_time(row),
                                "side": "buy",
                                "price": round(fill, 4),
                                "shares": buy_shares,
                                "fee": round(comm + stamp + xfer, 2),
                            }
                        )

        prev_target = target
        equity = cash + shares * price
        equity_curve.append(_equity_point(row, equity, target=target))

    closes = work["close"].astype(float)
    equities = [p["value"] for p in equity_curve]
    total_fees = (
        stats.total_commission + stats.total_stamp_duty + stats.total_transfer_fee + stats.total_slippage
    )
    metrics = _metrics(
        equities,
        capital_base,
        len(trades),
        bars_per_year=bars_per_year,
        round_trips=round_trips,
        total_fees=total_fees,
        closes=closes,
        warmup=warmup,
    )
    final_target = prev_target
    if final_target <= 1e-6:
        position = "flat"
    elif final_target >= 0.95:
        position = "long"
    else:
        position = "partial"
    last_row = work.iloc[-1]
    return {
        "metrics": metrics,
        "trades": trades,
        "equity_curve": equity_curve,
        "execution_rules": execution_rules_payload(fees=fees, board=board),
        "cost_summary": stats.to_dict(),
        "cost_model": {
            "market": "ashare",
            "commission_rate": fees.commission_rate,
            "stamp_duty_rate": fees.stamp_duty_rate,
            "slippage_bps": fees.slippage_bps,
            "total_fees": round(total_fees, 2),
        },
        "final_signal": {
            "position": position,
            "target_pct": final_target,
            "bar_time": _bar_time(last_row),
        },
    }
