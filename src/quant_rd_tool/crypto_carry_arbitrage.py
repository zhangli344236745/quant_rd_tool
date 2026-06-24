"""Binance spot–perp Cash & Carry scanner with paper position simulation."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.time_util import to_beijing_iso

DEFAULT_WATCHLIST = ["BTC", "ETH", "SOL", "BNB"]
CARRY_DIR = Path("data/crypto/carry")
SNAPSHOT_CACHE_TTL_SEC = 20.0
PositionStatus = Literal["open", "closed"]

_SNAPSHOT_CACHE: dict[str, tuple[float, dict[str, float]]] = {}


@dataclass
class CarryConfig:
    watchlist: list[str] = field(default_factory=lambda: list(DEFAULT_WATCHLIST))
    quote: str = "USDT"
    entry_threshold_apr: float = 0.15
    exit_threshold_apr: float = 0.05
    default_notional_usdt: float = 10_000.0
    spot_fee_pct: float = 0.001
    perp_fee_pct: float = 0.001
    slippage_pct: float = 0.0005
    testnet: bool = False


def compute_basis_bps(*, spot_mark: float, perp_mark: float) -> float:
    if spot_mark <= 0:
        raise ValueError("spot_mark must be positive")
    return (perp_mark - spot_mark) / spot_mark * 10_000


def compute_funding_apr(funding_rate: float) -> float:
    return funding_rate * 3 * 365


def compute_composite_apr(*, funding_apr: float, basis_bps: float) -> float:
    basis_apr_hint = basis_bps / 10_000 * 365
    return funding_apr + basis_apr_hint


def entry_alert(*, composite_apr: float, config: CarryConfig, has_open_position: bool) -> bool:
    if has_open_position:
        return False
    return composite_apr >= config.entry_threshold_apr


def exit_alert(*, composite_apr: float, funding_rate: float, config: CarryConfig) -> bool:
    return composite_apr <= config.exit_threshold_apr or funding_rate < 0


def estimate_open_cost_usdt(notional: float, config: CarryConfig) -> dict[str, float]:
    fees = notional * (config.spot_fee_pct + config.perp_fee_pct)
    slippage = notional * config.slippage_pct * 2
    return {
        "open_fees_usdt": round(fees, 4),
        "open_slippage_usdt": round(slippage, 4),
        "open_cost_usdt": round(fees + slippage, 4),
    }


def estimate_round_trip_cost_usdt(notional: float, config: CarryConfig) -> dict[str, float]:
    open_cost = estimate_open_cost_usdt(notional, config)
    close_fees = notional * (config.spot_fee_pct + config.perp_fee_pct)
    close_slippage = notional * config.slippage_pct * 2
    round_trip_fees = open_cost["open_fees_usdt"] + close_fees
    round_trip_slippage = open_cost["open_slippage_usdt"] + close_slippage
    return {
        **open_cost,
        "close_fees_usdt": round(close_fees, 4),
        "close_slippage_usdt": round(close_slippage, 4),
        "round_trip_fees_usdt": round(round_trip_fees, 4),
        "round_trip_slippage_usdt": round(round_trip_slippage, 4),
        "round_trip_cost_usdt": round(round_trip_fees + round_trip_slippage, 4),
    }


def build_carry_profit_estimate(
    *,
    notional_usdt: float,
    funding_rate: float,
    basis_bps: float,
    config: CarryConfig,
) -> dict[str, Any]:
    """USDT profit estimates for carry at given notional and current rates."""
    funding_apr = compute_funding_apr(funding_rate)
    basis_apr_hint = basis_bps / 10_000 * 365
    composite_apr = compute_composite_apr(funding_apr=funding_apr, basis_bps=basis_bps)
    funding_per_8h = notional_usdt * funding_rate
    funding_daily = funding_per_8h * 3
    costs = estimate_round_trip_cost_usdt(notional_usdt, config)
    open_cost = costs["open_cost_usdt"]
    open_fees = costs["open_fees_usdt"]
    round_trip_cost = costs["round_trip_cost_usdt"]
    breakeven_days: float | None
    if funding_daily > 0:
        breakeven_days = round(round_trip_cost / funding_daily, 2)
    else:
        breakeven_days = None
    return {
        "notional_usdt": round(notional_usdt, 2),
        "funding_per_8h_usdt": round(funding_per_8h, 4),
        "funding_daily_usdt": round(funding_daily, 4),
        "funding_7d_usdt": round(funding_daily * 7, 4),
        "funding_30d_usdt": round(funding_daily * 30, 4),
        "funding_annual_usdt": round(notional_usdt * funding_apr, 4),
        "basis_annual_hint_usdt": round(notional_usdt * basis_apr_hint, 4),
        "composite_annual_hint_usdt": round(notional_usdt * composite_apr, 4),
        "open_fees_usdt": open_fees,
        "open_cost_usdt": open_cost,
        "round_trip_cost_usdt": round_trip_cost,
        "net_daily_after_open_fee_usdt": round(funding_daily - open_fees, 4),
        "net_7d_after_open_cost_usdt": round(funding_daily * 7 - open_cost, 4),
        "net_30d_after_open_cost_usdt": round(funding_daily * 30 - open_cost, 4),
        "breakeven_days": breakeven_days,
    }


def build_carry_open_plan(
    symbol: str,
    *,
    notional_usdt: float,
    spot_mark: float,
    perp_mark: float,
    funding_rate: float,
    config: CarryConfig,
) -> dict[str, Any]:
    """Paper carry open: buy spot + short perp with equal base amount."""
    base = symbol.strip().upper()
    quote = config.quote
    spot_entry = spot_mark * (1 + config.slippage_pct)
    perp_entry = perp_mark * (1 - config.slippage_pct)
    base_amount = notional_usdt / spot_entry
    spot_fee = notional_usdt * config.spot_fee_pct
    perp_fee = notional_usdt * config.perp_fee_pct
    perp_notional = base_amount * perp_entry
    funding_per_8h = notional_usdt * funding_rate
    funding_daily = funding_per_8h * 3

    return {
        "symbol": base,
        "quote": quote,
        "notional_usdt": round(notional_usdt, 2),
        "base_amount": round(base_amount, 8),
        "steps": [
            {
                "order": 1,
                "market": "spot",
                "side": "buy",
                "side_label": "买入现货",
                "base_amount": round(base_amount, 8),
                "price": round(spot_entry, 8),
                "quote_amount_usdt": round(notional_usdt, 2),
                "fee_usdt": round(spot_fee, 4),
                "description": (
                    f"现货市场买入 {base_amount:.6f} {base}，成交价约 {spot_entry:.4f} {quote}，"
                    f"支出约 {notional_usdt:.2f} {quote} + 手续费 {spot_fee:.2f}"
                ),
            },
            {
                "order": 2,
                "market": "perp",
                "side": "short",
                "side_label": "做空永续",
                "base_amount": round(base_amount, 8),
                "price": round(perp_entry, 8),
                "quote_amount_usdt": round(perp_notional, 2),
                "fee_usdt": round(perp_fee, 4),
                "description": (
                    f"USDT 永续做空 {base_amount:.6f} {base}，成交价约 {perp_entry:.4f} {quote}，"
                    f"名义约 {perp_notional:.2f} {quote} + 手续费 {perp_fee:.2f}"
                ),
            },
        ],
        "summary": (
            f"Delta 中性：多头 {base_amount:.6f} {base} 现货 + 空头 {base_amount:.6f} {base} 永续，"
            f"名义各约 {notional_usdt:.0f} {quote}"
        ),
        "open_fees_usdt": round(spot_fee + perp_fee, 4),
        "expected_income": {
            "funding_per_8h_usdt": round(funding_per_8h, 4),
            "funding_daily_usdt": round(funding_daily, 4),
            "funding_7d_usdt": round(funding_daily * 7, 4),
            "funding_30d_usdt": round(funding_daily * 30, 4),
            "funding_annual_usdt": round(notional_usdt * compute_funding_apr(funding_rate), 4),
            "net_daily_after_open_fee_usdt": round(funding_daily - (spot_fee + perp_fee), 4),
        },
    }


def build_carry_close_plan(
    position: dict[str, Any],
    *,
    spot_mark: float,
    perp_mark: float,
    config: CarryConfig,
) -> dict[str, Any]:
    """Paper carry close: sell spot + cover perp short."""
    base = str(position["symbol"]).upper()
    quote = str(position.get("quote", config.quote))
    base_amount = float(position["base_amount"])
    spot_exit = spot_mark * (1 - config.slippage_pct)
    perp_exit = perp_mark * (1 + config.slippage_pct)
    spot_proceeds = base_amount * spot_exit
    perp_notional = base_amount * perp_exit
    spot_fee = spot_proceeds * config.spot_fee_pct
    perp_fee = perp_notional * config.perp_fee_pct

    return {
        "symbol": base,
        "quote": quote,
        "base_amount": round(base_amount, 8),
        "steps": [
            {
                "order": 1,
                "market": "spot",
                "side": "sell",
                "side_label": "卖出现货",
                "base_amount": round(base_amount, 8),
                "price": round(spot_exit, 8),
                "quote_amount_usdt": round(spot_proceeds, 2),
                "fee_usdt": round(spot_fee, 4),
                "description": (
                    f"现货市场卖出 {base_amount:.6f} {base}，成交价约 {spot_exit:.4f} {quote}，"
                    f"收回约 {spot_proceeds:.2f} {quote} − 手续费 {spot_fee:.2f}"
                ),
            },
            {
                "order": 2,
                "market": "perp",
                "side": "cover_short",
                "side_label": "平空永续",
                "base_amount": round(base_amount, 8),
                "price": round(perp_exit, 8),
                "quote_amount_usdt": round(perp_notional, 2),
                "fee_usdt": round(perp_fee, 4),
                "description": (
                    f"USDT 永续买入平空 {base_amount:.6f} {base}，成交价约 {perp_exit:.4f} {quote}，"
                    f"名义约 {perp_notional:.2f} {quote} + 手续费 {perp_fee:.2f}"
                ),
            },
        ],
        "summary": f"平掉双腿：卖出全部现货多头并回补永续空头 {base_amount:.6f} {base}",
        "close_fees_usdt": round(spot_fee + perp_fee, 4),
    }


def build_position_live_status(
    position: dict[str, Any],
    snapshot: dict[str, float],
    config: CarryConfig,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Open position legs + mark-to-market PnL breakdown."""
    dt = now or datetime.now(UTC)
    funding_rate = float(snapshot["funding_rate"])
    accrual = _simulate_pending_accrual(position, now=dt, funding_rate=funding_rate)
    pnl = _compute_close_pnl(
        position,
        config,
        spot_mark=float(snapshot["spot_mark"]),
        perp_mark=float(snapshot["perp_mark"]),
        accrued_funding=accrual["accrued_funding_total"],
    )
    base_amount = float(position["base_amount"])
    spot_entry = float(position["spot_entry"])
    perp_entry = float(position["perp_entry"])
    spot_mark = float(snapshot["spot_mark"])
    perp_mark = float(snapshot["perp_mark"])
    spot_leg_mtm = base_amount * (spot_mark - spot_entry)
    perp_leg_mtm = base_amount * (perp_entry - perp_mark)

    open_plan = {
        "symbol": position["symbol"],
        "quote": position.get("quote", config.quote),
        "notional_usdt": position["notional_usdt"],
        "base_amount": position["base_amount"],
        "summary": (
            f"持仓：多头 {base_amount:.6f} {position['symbol']} 现货 + "
            f"空头 {base_amount:.6f} {position['symbol']} 永续"
        ),
        "steps": [
            {
                "order": 1,
                "market": "spot",
                "side": "buy",
                "side_label": "已买入现货",
                "base_amount": position["base_amount"],
                "price": position["spot_entry"],
                "quote_amount_usdt": position["notional_usdt"],
                "description": f"持仓 {base_amount:.6f} {position['symbol']} 现货，入场价 {spot_entry:.4f}",
            },
            {
                "order": 2,
                "market": "perp",
                "side": "short",
                "side_label": "已做空永续",
                "base_amount": position["base_amount"],
                "price": position["perp_entry"],
                "quote_amount_usdt": round(base_amount * perp_entry, 2),
                "description": f"空头 {base_amount:.6f} {position['symbol']} 永续，入场价 {perp_entry:.4f}",
            },
        ],
    }

    return {
        "open_plan": open_plan,
        "current_spot_mark": round(spot_mark, 8),
        "current_perp_mark": round(perp_mark, 8),
        "pending_funding_usdt": accrual["pending_funding_usdt"],
        "pnl_breakdown": {
            "accrued_funding_usdt": pnl["accrued_funding"],
            "spot_leg_mtm_usdt": round(spot_leg_mtm, 4),
            "perp_leg_mtm_usdt": round(perp_leg_mtm, 4),
            "basis_pnl_if_close_usdt": pnl["basis_pnl"],
            "open_fees_paid_usdt": round(float(position.get("total_fees", 0)), 4),
            "close_fees_est_usdt": pnl["close_fees_usdt"],
            "unrealized_pnl_if_close_now_usdt": pnl["realized_pnl"],
        },
        "expected_income_if_hold": {
            "funding_per_8h_usdt": round(float(position["notional_usdt"]) * funding_rate, 4),
            "funding_daily_usdt": round(float(position["notional_usdt"]) * funding_rate * 3, 4),
        },
    }


def build_carry_risk_warnings(
    *,
    funding_rate: float,
    basis_bps: float,
    composite_apr: float,
    breakeven_days: float | None,
    config: CarryConfig,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if funding_rate < 0:
        warnings.append(
            {
                "level": "high",
                "title": "Funding 为负",
                "detail": "当前做空永续需支付 funding，持仓可能持续亏损。",
            }
        )
    if composite_apr < config.entry_threshold_apr:
        warnings.append(
            {
                "level": "medium",
                "title": "综合收益低于入场阈值",
                "detail": f"当前 composite APR {composite_apr:.2%} 低于设定阈值 {config.entry_threshold_apr:.2%}。",
            }
        )
    if basis_bps > 50:
        warnings.append(
            {
                "level": "medium",
                "title": "基差偏高",
                "detail": "永续显著溢价，若基差回落，平仓时可能抵消部分 funding 收益。",
            }
        )
    if basis_bps < -30:
        warnings.append(
            {
                "level": "medium",
                "title": "永续贴水",
                "detail": "永续低于现货，Cash & Carry 结构下基差收敛方向可能不利。",
            }
        )
    if breakeven_days is not None and breakeven_days > 30:
        warnings.append(
            {
                "level": "medium",
                "title": "收回成本周期较长",
                "detail": f"按当前 funding 估算，约需 {breakeven_days:.1f} 天才能覆盖开平仓手续费与滑点。",
            }
        )
    warnings.extend(
        [
            {
                "level": "info",
                "title": "Funding 每 8 小时变动",
                "detail": "Binance funding rate 每 8 小时结算且可能翻转，历史 rate 不代表未来。",
            },
            {
                "level": "info",
                "title": "基差收益仅为参考",
                "detail": "basis APR 按当前价差年化，不保证向现货收敛或维持。",
            },
            {
                "level": "info",
                "title": "纸面模拟非实盘",
                "detail": "未计入借币/保证金利息、极端行情与交易所风险；实盘结果可能显著不同。",
            },
        ]
    )
    return warnings


def build_carry_close_risk_warnings(
    *,
    funding_rate: float,
    composite_apr: float,
    exit_alert_triggered: bool,
    realized_pnl: float,
    basis_change_bps: float,
    hold_days: float,
    breakeven_days: float | None,
    config: CarryConfig,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if exit_alert_triggered:
        warnings.append(
            {
                "level": "high",
                "title": "已触发退出告警",
                "detail": "综合 APR 低于退出阈值或 funding 转负，继续持仓风险上升。",
            }
        )
    if funding_rate < 0:
        warnings.append(
            {
                "level": "high",
                "title": "Funding 为负",
                "detail": "当前 rate 下做空永续需支付 funding，平仓可停止进一步 bleed。",
            }
        )
    if realized_pnl < 0:
        warnings.append(
            {
                "level": "high",
                "title": "预估平仓亏损",
                "detail": f"按当前行情估算 realized PnL 为 {realized_pnl:.2f} USDT。",
            }
        )
    if basis_change_bps > 10:
        warnings.append(
            {
                "level": "medium",
                "title": "基差扩大",
                "detail": f"相对入场 basis 扩大 {basis_change_bps:.1f} bps，可能侵蚀 funding 收益。",
            }
        )
    if breakeven_days is not None and hold_days < breakeven_days and realized_pnl < 0:
        warnings.append(
            {
                "level": "medium",
                "title": "持仓时间短于成本回收期",
                "detail": f"已持仓 {hold_days:.1f} 天，估算收回开平仓成本约需 {breakeven_days:.1f} 天。",
            }
        )
    if composite_apr <= config.exit_threshold_apr:
        warnings.append(
            {
                "level": "medium",
                "title": "综合收益偏低",
                "detail": f"当前 composite APR {composite_apr:.2%} 不高于退出阈值 {config.exit_threshold_apr:.2%}。",
            }
        )
    warnings.extend(
        [
            {
                "level": "info",
                "title": "估价为静态快照",
                "detail": "实际平仓价受滑点与行情波动影响，与预览可能存在偏差。",
            },
            {
                "level": "info",
                "title": "Pending funding 将在平仓时入账",
                "detail": "预览含自上次 funding 边界以来尚未入账的估算 funding。",
            },
        ]
    )
    return warnings


def _simulate_pending_accrual(
    position: dict[str, Any],
    *,
    now: datetime,
    funding_rate: float,
) -> dict[str, float]:
    periods = _count_funding_periods(position.get("last_funding_ts"), now)
    pending = float(position["notional_usdt"]) * funding_rate * periods
    accrued = round(float(position.get("accrued_funding", 0.0)) + pending, 6)
    return {
        "pending_periods": float(periods),
        "pending_funding_usdt": round(pending, 6),
        "accrued_funding_total": accrued,
    }


def _compute_close_pnl(
    position: dict[str, Any],
    cfg: CarryConfig,
    *,
    spot_mark: float,
    perp_mark: float,
    accrued_funding: float,
) -> dict[str, Any]:
    notional = float(position["notional_usdt"])
    spot_exit = spot_mark * (1 - cfg.slippage_pct)
    perp_exit = perp_mark * (1 + cfg.slippage_pct)
    exit_basis_bps = compute_basis_bps(spot_mark=spot_exit, perp_mark=perp_exit)
    entry_basis_bps = float(position["entry_basis_bps"])
    basis_change_bps = exit_basis_bps - entry_basis_bps
    basis_pnl = (entry_basis_bps - exit_basis_bps) * notional / 10_000
    close_fees = notional * (cfg.spot_fee_pct + cfg.perp_fee_pct)
    total_fees = float(position["total_fees"]) + close_fees
    realized = accrued_funding + basis_pnl - total_fees
    return {
        "entry_basis_bps": round(entry_basis_bps, 4),
        "exit_basis_bps": round(exit_basis_bps, 4),
        "basis_change_bps": round(basis_change_bps, 4),
        "basis_pnl": round(basis_pnl, 6),
        "accrued_funding": round(accrued_funding, 6),
        "close_fees_usdt": round(close_fees, 6),
        "total_fees_usdt": round(total_fees, 6),
        "realized_pnl": round(realized, 6),
        "spot_exit": round(spot_exit, 8),
        "perp_exit": round(perp_exit, 8),
    }


def preview_close_paper_carry(
    position_id: str,
    *,
    config: CarryConfig | None = None,
    snapshot: dict[str, float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    position = _load_position(position_id)
    if position.get("status") != "open":
        raise ValueError(f"position not open: {position_id}")

    base = str(position["symbol"]).upper()
    dt = now or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    if snapshot is None:
        snapshot = fetch_market_snapshot(base, quote=cfg.quote, testnet=cfg.testnet)

    spot_mark = float(snapshot["spot_mark"])
    perp_mark = float(snapshot["perp_mark"])
    funding_rate = float(snapshot["funding_rate"])
    basis_bps = compute_basis_bps(spot_mark=spot_mark, perp_mark=perp_mark)
    funding_apr = compute_funding_apr(funding_rate)
    composite_apr = compute_composite_apr(funding_apr=funding_apr, basis_bps=basis_bps)
    exit_alert_triggered = exit_alert(
        composite_apr=composite_apr,
        funding_rate=funding_rate,
        config=cfg,
    )

    accrual = _simulate_pending_accrual(position, now=dt, funding_rate=funding_rate)
    pnl = _compute_close_pnl(
        position,
        cfg,
        spot_mark=spot_mark,
        perp_mark=perp_mark,
        accrued_funding=accrual["accrued_funding_total"],
    )

    entry_dt = _parse_ts(str(position.get("entry_ts")))
    hold_days = round(max((dt - entry_dt).total_seconds(), 0) / 86400, 2)
    notional = float(position["notional_usdt"])
    costs = estimate_round_trip_cost_usdt(notional, cfg)
    funding_daily = notional * funding_rate * 3
    breakeven_days = round(costs["round_trip_cost_usdt"] / funding_daily, 2) if funding_daily > 0 else None
    close_plan = build_carry_close_plan(
        position,
        spot_mark=spot_mark,
        perp_mark=perp_mark,
        config=cfg,
    )
    live_status = build_position_live_status(position, snapshot, cfg, now=dt)

    return {
        "position_id": position_id,
        "symbol": base,
        "notional_usdt": round(notional, 2),
        "entry_ts": position.get("entry_ts"),
        "hold_days": hold_days,
        "can_close": True,
        "exit_alert": exit_alert_triggered,
        "market": {
            "spot_mark": round(spot_mark, 8),
            "perp_mark": round(perp_mark, 8),
            "basis_bps": round(basis_bps, 4),
            "funding_rate": round(funding_rate, 8),
            "funding_apr": round(funding_apr, 6),
            "composite_apr": round(composite_apr, 6),
        },
        "position_snapshot": {
            "accrued_funding_booked": round(float(position.get("accrued_funding", 0.0)), 6),
            "pending_funding_usdt": accrual["pending_funding_usdt"],
            "pending_periods": int(accrual["pending_periods"]),
            "entry_basis_bps": pnl["entry_basis_bps"],
        },
        "pnl_estimate": {
            **pnl,
            "open_fees_paid_usdt": round(float(position.get("total_fees", 0.0)), 6),
            "funding_component_usdt": pnl["accrued_funding"],
            "fee_component_usdt": -pnl["total_fees_usdt"],
        },
        "execution_plan": close_plan,
        "open_legs": live_status["open_plan"],
        "pnl_breakdown": live_status["pnl_breakdown"],
        "risk_warnings": build_carry_close_risk_warnings(
            funding_rate=funding_rate,
            composite_apr=composite_apr,
            exit_alert_triggered=exit_alert_triggered,
            realized_pnl=float(pnl["realized_pnl"]),
            basis_change_bps=float(pnl["basis_change_bps"]),
            hold_days=hold_days,
            breakeven_days=breakeven_days,
            config=cfg,
        ),
        "disclaimer": "平仓预览含 pending funding 估算；确认后将写入账本并关闭仓位。",
    }


def preview_paper_carry(
    symbol: str,
    notional_usdt: float | None = None,
    *,
    config: CarryConfig | None = None,
    snapshot: dict[str, float] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    base = symbol.strip().upper()
    if base not in [s.upper() for s in cfg.watchlist]:
        raise ValueError(f"symbol not in watchlist: {base}")

    notional = float(notional_usdt if notional_usdt is not None else cfg.default_notional_usdt)
    if notional <= 0:
        raise ValueError("notional_usdt must be positive")

    if snapshot is None:
        snapshot = fetch_market_snapshot(base, quote=cfg.quote, testnet=cfg.testnet)

    spot_mark = float(snapshot["spot_mark"])
    perp_mark = float(snapshot["perp_mark"])
    funding_rate = float(snapshot["funding_rate"])
    basis_bps = compute_basis_bps(spot_mark=spot_mark, perp_mark=perp_mark)
    funding_apr = compute_funding_apr(funding_rate)
    composite_apr = compute_composite_apr(funding_apr=funding_apr, basis_bps=basis_bps)

    profit_estimate = build_carry_profit_estimate(
        notional_usdt=notional,
        funding_rate=funding_rate,
        basis_bps=basis_bps,
        config=cfg,
    )
    costs = estimate_round_trip_cost_usdt(notional, cfg)
    breakeven_days = profit_estimate["breakeven_days"]

    has_open = base in open_positions_by_symbol()
    open_plan = build_carry_open_plan(
        base,
        notional_usdt=notional,
        spot_mark=spot_mark,
        perp_mark=perp_mark,
        funding_rate=funding_rate,
        config=cfg,
    )
    return {
        "symbol": base,
        "notional_usdt": round(notional, 2),
        "has_open_position": has_open,
        "can_open": not has_open,
        "market": {
            "spot_mark": round(spot_mark, 8),
            "perp_mark": round(perp_mark, 8),
            "basis_bps": round(basis_bps, 4),
            "funding_rate": round(funding_rate, 8),
            "funding_apr": round(funding_apr, 6),
            "basis_apr_hint": round(basis_bps / 10_000 * 365, 6),
            "composite_apr": round(composite_apr, 6),
        },
        "profit_estimate": profit_estimate,
        "cost_breakdown": costs,
        "execution_plan": open_plan,
        "risk_warnings": build_carry_risk_warnings(
            funding_rate=funding_rate,
            basis_bps=basis_bps,
            composite_apr=composite_apr,
            breakeven_days=breakeven_days,
            config=cfg,
        ),
        "disclaimer": "以上为基于当前行情与费率的静态估算，不构成投资建议；funding 与基差会实时变化。",
    }


def _config_path() -> Path:
    return CARRY_DIR / "config.json"


def _positions_dir() -> Path:
    return CARRY_DIR / "positions"


def _events_path() -> Path:
    return CARRY_DIR / "events.jsonl"


def _snapshots_path() -> Path:
    return CARRY_DIR / "snapshots.jsonl"


def load_config() -> CarryConfig:
    path = _config_path()
    if not path.exists():
        return CarryConfig()
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    watchlist = data.get("watchlist") or list(DEFAULT_WATCHLIST)
    return CarryConfig(
        watchlist=[str(s).upper() for s in watchlist],
        quote=str(data.get("quote", "USDT")).upper(),
        entry_threshold_apr=float(data.get("entry_threshold_apr", 0.15)),
        exit_threshold_apr=float(data.get("exit_threshold_apr", 0.05)),
        default_notional_usdt=float(data.get("default_notional_usdt", 10_000.0)),
        spot_fee_pct=float(data.get("spot_fee_pct", 0.001)),
        perp_fee_pct=float(data.get("perp_fee_pct", 0.001)),
        slippage_pct=float(data.get("slippage_pct", 0.0005)),
        testnet=bool(data.get("testnet", False)),
    )


def save_config(config: CarryConfig) -> CarryConfig:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def _perp_symbol(base: str, quote: str = "USDT") -> str:
    return f"{base.upper()}/{quote}:{quote}"


def _parse_ts(ts: str | None) -> datetime:
    if not ts:
        return datetime.now(UTC)
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso_now(now: datetime | None = None) -> str:
    return to_beijing_iso(now)


def _floor_funding_boundary(dt: datetime) -> datetime:
    dt = dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    hour = dt.hour - (dt.hour % 8)
    return dt.replace(hour=hour)


def _count_funding_periods(last_ts: str | None, now: datetime) -> int:
    start = _floor_funding_boundary(_parse_ts(last_ts))
    end = _floor_funding_boundary(now)
    if end <= start:
        return 0
    return int((end - start).total_seconds() // (8 * 3600))


def _append_event(event: dict[str, Any]) -> None:
    path = _events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def _append_snapshot(row: dict[str, Any]) -> None:
    path = _snapshots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _position_path(position_id: str) -> Path:
    return _positions_dir() / f"{position_id}.json"


def _load_position(position_id: str) -> dict[str, Any]:
    path = _position_path(position_id)
    if not path.exists():
        raise ValueError(f"position not found: {position_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_position(position: dict[str, Any]) -> dict[str, Any]:
    path = _position_path(str(position["id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(position, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return position


def list_positions(*, status: PositionStatus | None = None, limit: int = 50) -> list[dict[str, Any]]:
    root = _positions_dir()
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if status and row.get("status") != status:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def open_positions_by_symbol() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in list_positions(status="open", limit=500):
        sym = str(row.get("symbol", "")).upper()
        if sym:
            out[sym] = row
    return out


def clear_snapshot_cache() -> None:
    _SNAPSHOT_CACHE.clear()


def _snapshot_cache_key(base: str, *, quote: str, testnet: bool) -> str:
    return f"{base.upper()}:{quote.upper()}:{'1' if testnet else '0'}"


def _exchange_common_kwargs(*, testnet: bool) -> dict[str, Any]:
    from quant_rd_tool.config import settings

    return {
        "api_base": settings.binance_api_base,
        "http_proxy": settings.http_proxy,
        "https_proxy": settings.https_proxy,
        "testnet": testnet,
    }


def _parse_ticker_marks(
    spot_ticker: dict[str, Any],
    perp_ticker: dict[str, Any],
    funding: dict[str, Any],
) -> dict[str, float]:
    spot_mark = float(spot_ticker.get("last") or spot_ticker.get("close") or 0.0)
    perp_mark = float(
        perp_ticker.get("mark")
        or perp_ticker.get("last")
        or perp_ticker.get("close")
        or 0.0
    )
    funding_rate = float(funding.get("fundingRate") or funding.get("funding_rate") or 0.0)
    if spot_mark <= 0 or perp_mark <= 0:
        raise ValueError(f"invalid marks: spot={spot_mark}, perp={perp_mark}")
    return {
        "spot_mark": spot_mark,
        "perp_mark": perp_mark,
        "funding_rate": funding_rate,
    }


def _cache_snapshot(base: str, snapshot: dict[str, float], *, quote: str, testnet: bool) -> None:
    _SNAPSHOT_CACHE[_snapshot_cache_key(base, quote=quote, testnet=testnet)] = (time.time(), snapshot)


def _get_cached_snapshot(base: str, *, quote: str, testnet: bool) -> dict[str, float] | None:
    key = _snapshot_cache_key(base, quote=quote, testnet=testnet)
    cached = _SNAPSHOT_CACHE.get(key)
    if not cached:
        return None
    ts, snapshot = cached
    if time.time() - ts > SNAPSHOT_CACHE_TTL_SEC:
        _SNAPSHOT_CACHE.pop(key, None)
        return None
    return snapshot


def fetch_watchlist_snapshots(
    symbols: list[str],
    *,
    quote: str = "USDT",
    testnet: bool = False,
) -> dict[str, dict[str, float]]:
    """Batch-fetch spot/perp marks + funding for watchlist symbols (cached, shared ccxt clients)."""
    bases = [s.strip().upper() for s in symbols if s and str(s).strip()]
    result: dict[str, dict[str, float]] = {}
    missing: list[str] = []
    for base in bases:
        cached = _get_cached_snapshot(base, quote=quote, testnet=testnet)
        if cached is not None:
            result[base] = cached
        else:
            missing.append(base)
    if not missing:
        return result

    common = _exchange_common_kwargs(testnet=testnet)
    spot_ex = cxt.create_exchange("binance", market_type="spot", **common)
    fut_ex = cxt.create_exchange("binance", market_type="future", **common)

    spot_pairs = {base: cxt.to_ccxt_symbol(base, quote) for base in missing}
    perp_pairs = {base: _perp_symbol(base, quote) for base in missing}
    spot_symbols = list(spot_pairs.values())
    perp_symbols = list(perp_pairs.values())

    spot_tickers: dict[str, Any] = {}
    perp_tickers: dict[str, Any] = {}
    funding_rates: dict[str, Any] = {}
    try:
        spot_tickers = spot_ex.fetch_tickers(spot_symbols)
    except Exception:
        spot_tickers = {}
    try:
        perp_tickers = fut_ex.fetch_tickers(perp_symbols)
    except Exception:
        perp_tickers = {}
    try:
        funding_rates = fut_ex.fetch_funding_rates(perp_symbols)
    except Exception:
        funding_rates = {}

    for base in missing:
        sp = spot_pairs[base]
        pp = perp_pairs[base]
        try:
            spot_ticker = spot_tickers.get(sp)
            perp_ticker = perp_tickers.get(pp)
            funding = funding_rates.get(pp)
            if spot_ticker is None:
                spot_ticker = spot_ex.fetch_ticker(sp)
            if perp_ticker is None:
                perp_ticker = fut_ex.fetch_ticker(pp)
            if funding is None:
                funding = fut_ex.fetch_funding_rate(pp)
            snapshot = _parse_ticker_marks(spot_ticker, perp_ticker, funding)
            result[base] = snapshot
            _cache_snapshot(base, snapshot, quote=quote, testnet=testnet)
        except Exception:
            continue
    return result


def fetch_market_snapshot(symbol: str, *, quote: str = "USDT", testnet: bool = False) -> dict[str, float]:
    base = symbol.strip().upper()
    cached = _get_cached_snapshot(base, quote=quote, testnet=testnet)
    if cached is not None:
        return cached
    snapshots = fetch_watchlist_snapshots([base], quote=quote, testnet=testnet)
    if base not in snapshots:
        raise ValueError(f"failed to fetch market snapshot for {base}")
    return snapshots[base]


def build_opportunity(
    symbol: str,
    *,
    snapshot: dict[str, float],
    config: CarryConfig,
    has_open_position: bool,
    ts: str | None = None,
) -> dict[str, Any]:
    basis_bps = compute_basis_bps(spot_mark=snapshot["spot_mark"], perp_mark=snapshot["perp_mark"])
    funding_rate = float(snapshot["funding_rate"])
    funding_apr = compute_funding_apr(funding_rate)
    composite_apr = compute_composite_apr(funding_apr=funding_apr, basis_bps=basis_bps)
    notional = config.default_notional_usdt
    profit_estimate = build_carry_profit_estimate(
        notional_usdt=notional,
        funding_rate=funding_rate,
        basis_bps=basis_bps,
        config=config,
    )
    return {
        "symbol": symbol.upper(),
        "notional_usdt": round(notional, 2),
        "spot_mark": round(snapshot["spot_mark"], 8),
        "perp_mark": round(snapshot["perp_mark"], 8),
        "basis_bps": round(basis_bps, 4),
        "funding_rate": round(funding_rate, 8),
        "funding_apr": round(funding_apr, 6),
        "basis_apr_hint": round(basis_bps / 10_000 * 365, 6),
        "composite_apr": round(composite_apr, 6),
        "profit_estimate": profit_estimate,
        "entry_alert": entry_alert(
            composite_apr=composite_apr,
            config=config,
            has_open_position=has_open_position,
        ),
        "exit_alert": exit_alert(
            composite_apr=composite_apr,
            funding_rate=funding_rate,
            config=config,
        ),
        "has_open_position": has_open_position,
        "ts": ts or _iso_now(),
        "carry_plan": build_carry_open_plan(
            symbol.upper(),
            notional_usdt=config.default_notional_usdt,
            spot_mark=float(snapshot["spot_mark"]),
            perp_mark=float(snapshot["perp_mark"]),
            funding_rate=float(snapshot["funding_rate"]),
            config=config,
        ),
    }


def scan_watchlist(
    config: CarryConfig | None = None,
    *,
    now: datetime | None = None,
    record_snapshot: bool = True,
) -> list[dict[str, Any]]:
    cfg = config or load_config()
    symbols = [s.strip().upper() for s in cfg.watchlist if s and str(s).strip()]
    snapshots = fetch_watchlist_snapshots(symbols, quote=cfg.quote, testnet=cfg.testnet)
    funding_rates = {sym: float(snap["funding_rate"]) for sym, snap in snapshots.items()}
    accrue_open_positions(cfg, now=now, funding_rates=funding_rates)
    open_map = open_positions_by_symbol()
    rows: list[dict[str, Any]] = []
    ts = _iso_now(now)
    for base in symbols:
        if base in snapshots:
            row = build_opportunity(
                base,
                snapshot=snapshots[base],
                config=cfg,
                has_open_position=base in open_map,
                ts=ts,
            )
        else:
            row = {
                "symbol": base,
                "error": "market snapshot unavailable",
                "has_open_position": base in open_map,
                "entry_alert": False,
                "exit_alert": False,
                "ts": ts,
            }
        rows.append(row)
        if record_snapshot and "error" not in row:
            _append_snapshot(row)
    return rows


def open_paper_carry(
    symbol: str,
    notional_usdt: float | None,
    *,
    config: CarryConfig | None = None,
    spot_mark: float | None = None,
    perp_mark: float | None = None,
    funding_rate: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    base = symbol.strip().upper()
    if base not in [s.upper() for s in cfg.watchlist]:
        raise ValueError(f"symbol not in watchlist: {base}")
    if base in open_positions_by_symbol():
        raise ValueError(f"already has open paper carry for {base}")

    notional = float(notional_usdt if notional_usdt is not None else cfg.default_notional_usdt)
    if notional <= 0:
        raise ValueError("notional_usdt must be positive")

    if spot_mark is None or perp_mark is None or funding_rate is None:
        if any(v is not None for v in (spot_mark, perp_mark, funding_rate)):
            raise ValueError("spot_mark, perp_mark, funding_rate must all be provided together")
        snap = fetch_market_snapshot(base, quote=cfg.quote, testnet=cfg.testnet)
        spot_mark = float(snap["spot_mark"])
        perp_mark = float(snap["perp_mark"])
        funding_rate = float(snap["funding_rate"])
    else:
        spot_mark = float(spot_mark)
        perp_mark = float(perp_mark)
        funding_rate = float(funding_rate)

    spot_entry = spot_mark * (1 + cfg.slippage_pct)
    perp_entry = perp_mark * (1 - cfg.slippage_pct)
    base_amount = notional / spot_entry
    open_fees = notional * (cfg.spot_fee_pct + cfg.perp_fee_pct)
    entry_basis_bps = compute_basis_bps(spot_mark=spot_entry, perp_mark=perp_entry)
    entry_ts = _iso_now(now)
    position = {
        "id": str(uuid.uuid4()),
        "symbol": base,
        "quote": cfg.quote,
        "notional_usdt": round(notional, 2),
        "base_amount": round(base_amount, 10),
        "spot_entry": round(spot_entry, 8),
        "perp_entry": round(perp_entry, 8),
        "entry_basis_bps": round(entry_basis_bps, 4),
        "entry_ts": entry_ts,
        "status": "open",
        "accrued_funding": 0.0,
        "total_fees": round(open_fees, 6),
        "last_funding_ts": entry_ts,
        "closed_ts": None,
        "realized_pnl": None,
    }
    execution_plan = build_carry_open_plan(
        base,
        notional_usdt=notional,
        spot_mark=spot_mark,
        perp_mark=perp_mark,
        funding_rate=funding_rate,
        config=cfg,
    )
    position["execution_plan"] = execution_plan
    _save_position(position)
    _append_event(
        {
            "type": "open",
            "position_id": position["id"],
            "symbol": base,
            "notional_usdt": notional,
            "spot_entry": position["spot_entry"],
            "perp_entry": position["perp_entry"],
            "funding_rate": funding_rate,
            "ts": entry_ts,
        }
    )
    return position


def close_paper_carry(
    position_id: str,
    *,
    config: CarryConfig | None = None,
    spot_mark: float | None = None,
    perp_mark: float | None = None,
    funding_rate: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    position = _load_position(position_id)
    if position.get("status") != "open":
        raise ValueError(f"position not open: {position_id}")

    base = str(position["symbol"]).upper()
    if spot_mark is None or perp_mark is None or funding_rate is None:
        if any(v is not None for v in (spot_mark, perp_mark, funding_rate)):
            raise ValueError("spot_mark, perp_mark, funding_rate must all be provided together")
        snap = fetch_market_snapshot(base, quote=cfg.quote, testnet=cfg.testnet)
        spot_mark = float(snap["spot_mark"])
        perp_mark = float(snap["perp_mark"])
        funding_rate = float(snap["funding_rate"])
    else:
        spot_mark = float(spot_mark)
        perp_mark = float(perp_mark)
        funding_rate = float(funding_rate)

    accrue_open_positions(cfg, now=now, funding_rates={base: funding_rate})
    position = _load_position(position_id)

    pnl = _compute_close_pnl(
        position,
        cfg,
        spot_mark=float(spot_mark),
        perp_mark=float(perp_mark),
        accrued_funding=float(position["accrued_funding"]),
    )
    closed_ts = _iso_now(now)

    position.update(
        {
            "status": "closed",
            "closed_ts": closed_ts,
            "exit_basis_bps": pnl["exit_basis_bps"],
            "spot_exit": pnl["spot_exit"],
            "perp_exit": pnl["perp_exit"],
            "basis_pnl": pnl["basis_pnl"],
            "total_fees": pnl["total_fees_usdt"],
            "realized_pnl": pnl["realized_pnl"],
        }
    )
    _save_position(position)
    _append_event(
        {
            "type": "close",
            "position_id": position_id,
            "symbol": base,
            "realized_pnl": position["realized_pnl"],
            "accrued_funding": position["accrued_funding"],
            "basis_pnl": position["basis_pnl"],
            "ts": closed_ts,
        }
    )
    return position


def accrue_open_positions(
    config: CarryConfig | None = None,
    *,
    now: datetime | None = None,
    funding_rates: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    cfg = config or load_config()
    dt = now or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    rates = funding_rates or {}
    updated: list[dict[str, Any]] = []
    for position in list_positions(status="open", limit=500):
        base = str(position["symbol"]).upper()
        periods = _count_funding_periods(position.get("last_funding_ts"), dt)
        if periods <= 0:
            continue
        rate = float(rates.get(base, 0.0))
        if base not in rates:
            try:
                snap = fetch_market_snapshot(base, quote=cfg.quote, testnet=cfg.testnet)
                rate = float(snap["funding_rate"])
            except Exception:
                rate = 0.0
        funding_pnl = float(position["notional_usdt"]) * rate * periods
        last_boundary = _floor_funding_boundary(dt)
        position["accrued_funding"] = round(float(position.get("accrued_funding", 0.0)) + funding_pnl, 6)
        position["last_funding_ts"] = last_boundary.isoformat()
        _save_position(position)
        _append_event(
            {
                "type": "accrue",
                "position_id": position["id"],
                "symbol": base,
                "periods": periods,
                "funding_rate": rate,
                "funding_pnl": round(funding_pnl, 6),
                "accrued_funding": position["accrued_funding"],
                "ts": _iso_now(dt),
            }
        )
        updated.append(position)
    return updated


def read_events(*, limit: int = 100) -> list[dict[str, Any]]:
    path = _events_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_carry_summary(
    config: CarryConfig | None = None,
    *,
    scan_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    open_rows = list_positions(status="open", limit=500)
    closed_rows = list_positions(status="closed", limit=500)
    items = scan_items or []
    entry_alerts = sum(1 for row in items if row.get("entry_alert"))
    exit_alerts = sum(
        1
        for row in items
        if row.get("has_open_position") and row.get("exit_alert")
    )
    total_realized = sum(float(r.get("realized_pnl") or 0.0) for r in closed_rows)
    total_accrued = sum(float(r.get("accrued_funding") or 0.0) for r in open_rows)
    return {
        "open_count": len(open_rows),
        "closed_count": len(closed_rows),
        "entry_alert_count": entry_alerts,
        "exit_alert_count": exit_alerts,
        "total_realized_pnl": round(total_realized, 6),
        "total_accrued_funding": round(total_accrued, 6),
        "recent_events": read_events(limit=20),
        "last_scan_ts": items[0]["ts"] if items else None,
    }


def carry_summary(
    config: CarryConfig | None = None,
    *,
    scan_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Local stats only; pass scan_items to avoid a second Binance scan."""
    return build_carry_summary(config, scan_items=scan_items)
