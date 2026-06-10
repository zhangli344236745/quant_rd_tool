"""PnL and stop-loss estimates for options strategy recommendations."""

from __future__ import annotations

import math
from typing import Any, Literal

from quant_rd_tool.crypto_options_data import fetch_mark_rows, parse_option_symbol
from quant_rd_tool.crypto_options_greeks import bs_analytical_greeks
from quant_rd_tool.crypto_options_portfolio_greeks import estimate_option_margin_usd

StrategyKind = Literal[
    "sell_straddle",
    "sell_strangle",
    "buy_straddle",
    "bull_call_spread",
    "bear_put_spread",
    "buy_call",
    "buy_put",
    "iron_condor",
    "wait",
]

_DISCLAIMER_PNL = (
    "盈亏与止损基于 mark 权利金及简化结构公式，未计手续费、滑点与保证金变动；"
    "止损为研究框架，不构成实盘交易指令。"
)

DEFAULT_CAPITAL_USD = 100_000.0
DEFAULT_OPTIONS_BUDGET_PCT = 0.05


def _mark_price_usd(raw: Any, spot: float) -> float:
    if raw is None:
        return max(spot * 0.02, 1.0)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return max(spot * 0.02, 1.0)
    if v <= 0:
        return max(spot * 0.02, 1.0)
    if spot > 1000 and v < 1.0:
        return v * spot
    return v


def _bs_premium_usd(spot: float, strike: float, *, iv: float, dte: float, opt_type: str) -> float:
    side = "C" if str(opt_type).upper().startswith("C") else "P"
    g = bs_analytical_greeks(spot, strike, iv=iv, dte_days=max(dte, 1.0), opt_type=side)  # type: ignore[arg-type]
    # Rough premium ≈ |delta| * spot * 0.15 for lack of full BS price — use intrinsic + time value est
    t = max(dte, 1.0) / 365.0
    intrinsic = max(0.0, spot - strike) if side == "C" else max(0.0, strike - spot)
    time_val = spot * iv * math.sqrt(t) * 0.4
    return max(intrinsic + time_val, spot * 0.003)


def build_price_index(
    *,
    base: str,
    spot: float,
    strike_report: dict[str, Any] | None = None,
    marks: list[dict[str, Any]] | None = None,
    default_iv: float = 0.5,
    dte: float = 14.0,
) -> dict[tuple[float, str], dict[str, Any]]:
    """Map (strike, C|P) -> {premium_usd, symbol, synthetic}."""
    idx: dict[tuple[float, str], dict[str, Any]] = {}
    base_u = base.upper()

    for row in (strike_report or {}).get("rows") or []:
        strike = row.get("strike")
        if strike is None:
            continue
        k = float(strike)
        mp = row.get("mark_price")
        sym = row.get("symbol") or ""
        side = "C"
        if sym and parse_option_symbol(str(sym)):
            side = parse_option_symbol(str(sym))["side"]
        elif row.get("implied") or row.get("model"):
            side = "C"
        if mp is not None:
            idx[(k, side)] = {
                "premium_usd": _mark_price_usd(mp, spot),
                "symbol": sym,
                "synthetic": False,
            }
        put_mp = row.get("put_mark_price")
        if put_mp is not None:
            idx[(k, "P")] = {
                "premium_usd": _mark_price_usd(put_mp, spot),
                "symbol": row.get("put_symbol"),
                "synthetic": False,
            }

    mark_rows = marks
    if mark_rows is None:
        try:
            mark_rows = fetch_mark_rows()
        except Exception:
            mark_rows = []

    for row in mark_rows or []:
        meta = parse_option_symbol(str(row.get("symbol") or ""))
        if not meta or meta["base"] != base_u:
            continue
        k = float(meta["strike"])
        side = meta["side"]
        key = (k, side)
        if key in idx:
            continue
        mp = row.get("markPrice")
        if mp is None:
            continue
        idx[key] = {
            "premium_usd": _mark_price_usd(mp, spot),
            "symbol": row.get("symbol"),
            "synthetic": False,
        }

    # BS fallback for legs missing from index
    return idx


def _leg_premium_usd(
    leg: dict[str, Any],
    *,
    price_index: dict[tuple[float, str], dict[str, Any]],
    spot: float,
    iv: float,
    dte: float,
) -> tuple[float, bool]:
    opt_type = str(leg.get("type") or "C").upper()[:1]
    strike = float(leg.get("strike") or spot)
    ent = price_index.get((strike, opt_type))
    if ent:
        return float(ent["premium_usd"]), bool(ent.get("synthetic"))
    prem = _bs_premium_usd(spot, strike, iv=iv, dte=dte, opt_type=opt_type)
    return prem, True


def _leg_cash_flow(premium: float, side: str) -> float:
    """Positive = credit received, negative = debit paid (per 1 coin contract)."""
    if str(side).upper() in ("S", "SELL", "SHORT"):
        return premium
    return -premium


def _intrinsic(spot: float, strike: float, opt_type: str) -> float:
    if opt_type == "P":
        return max(0.0, strike - spot)
    return max(0.0, spot - strike)


def _pnl_at_spot(
    legs: list[dict[str, Any]],
    leg_flows: list[tuple[float, str, float, str]],
    spot_new: float,
) -> float:
    """Expiry-style PnL at spot_new (per 1 coin)."""
    net_open = sum(flow for flow, *_ in leg_flows)
    close = 0.0
    for flow, opt_type, strike, side in leg_flows:
        intr = _intrinsic(spot_new, strike, opt_type)
        if str(side).upper() in ("S", "SELL", "SHORT"):
            close -= intr
        else:
            close += intr
    return net_open + close


def _stop_loss_for_kind(
    kind: str,
    *,
    spot: float,
    dte: float,
    net_cash_usd: float,
    max_loss_usd: float | None,
    legs: list[dict[str, Any]],
    leg_flows: list[tuple[float, str, float, str]],
) -> dict[str, Any]:
    notes: list[str] = []
    premium_stop: float | None = None
    spot_levels: list[float] = []
    time_stop = max(7, int(dte * 0.5)) if dte else 7
    primary = ""

    debit = -net_cash_usd if net_cash_usd < 0 else 0.0
    credit = net_cash_usd if net_cash_usd > 0 else 0.0

    if kind in ("buy_call", "buy_put", "buy_straddle", "bull_call_spread", "bear_put_spread"):
        if debit > 0:
            premium_stop = round(debit * 0.5, 2)
            primary = f"权利金亏损达净支出 {premium_stop:,.0f} USD（约 50%）时止损"
            notes.append("买方时间价值损耗加速时，宜提前减仓而非扛到到期。")
        if dte and dte <= 14:
            time_stop = max(3, int(dte * 0.35))
            notes.append(f"剩余 DTE ≤ {time_stop} 且未盈利，考虑时间止损。")
    elif kind in ("sell_straddle", "sell_strangle", "iron_condor"):
        if credit > 0:
            premium_stop = round(credit * 2.0, 2)
            primary = f"浮亏达收取权利金 2 倍（约 {premium_stop:,.0f} USD）时止损"
        for leg in legs:
            if str(leg.get("side")).upper() in ("S", "SELL", "SHORT"):
                k = float(leg.get("strike") or 0)
                if k > 0:
                    spot_levels.append(k)
        if spot_levels:
            notes.append("现货收盘有效突破卖出腿行权价时，考虑减仓或对冲 Delta。")
    else:
        primary = "观望策略，无期权腿止损线。"
        premium_stop = None
        time_stop = 0

    if max_loss_usd and debit > 0:
        notes.append(f"结构最大亏损约 {max_loss_usd:,.0f} USD/合约，不宜扛满。")

    return {
        "primary_rule": primary or "按仓位纪律设置止损。",
        "premium_stop_usd": premium_stop,
        "spot_stop_levels": [round(x, 2) for x in sorted(set(spot_levels))],
        "time_stop_dte": time_stop if kind != "wait" else None,
        "notes": notes,
    }


def _compute_kind_pnl(
    kind: str,
    legs: list[dict[str, Any]],
    leg_flows: list[tuple[float, str, float, str]],
    *,
    spot: float,
    dte: float,
) -> dict[str, Any]:
    net_cash = sum(f for f, *_ in leg_flows)
    max_profit: float | None = None
    max_loss: float | None = None
    breakevens: list[float] = []
    unlimited_profit = False
    unlimited_loss = False

    if kind == "buy_call":
        debit = -net_cash
        max_loss = debit
        unlimited_profit = True
        breakevens = [spot + debit] if debit > 0 else []

    elif kind == "buy_put":
        debit = -net_cash
        max_loss = debit
        k = float(legs[0].get("strike") or spot) if legs else spot
        max_profit = max(k - debit, 0.0)
        breakevens = [k - debit] if debit > 0 else []

    elif kind == "bull_call_spread" and len(leg_flows) >= 2:
        longs = [lf for lf in leg_flows if lf[3] not in ("S", "SELL", "SHORT")]
        shorts = [lf for lf in leg_flows if lf[3] in ("S", "SELL", "SHORT")]
        if longs and shorts:
            k_low = min(longs[0][2], shorts[0][2])
            k_high = max(longs[0][2], shorts[0][2])
            debit = -net_cash
            width = k_high - k_low
            max_loss = max(debit, 0.0)
            max_profit = max(width - debit, 0.0)
            breakevens = [k_low + debit] if debit > 0 else []

    elif kind == "bear_put_spread" and len(leg_flows) >= 2:
        longs = [lf for lf in leg_flows if lf[3] not in ("S", "SELL", "SHORT")]
        shorts = [lf for lf in leg_flows if lf[3] in ("S", "SELL", "SHORT")]
        if longs and shorts:
            k_high = max(longs[0][2], shorts[0][2])
            k_low = min(longs[0][2], shorts[0][2])
            debit = -net_cash
            width = k_high - k_low
            max_loss = max(debit, 0.0)
            max_profit = max(width - debit, 0.0)
            breakevens = [k_high - debit] if debit > 0 else []

    elif kind in ("sell_straddle", "sell_strangle"):
        credit = net_cash
        max_profit = credit
        unlimited_loss = True
        if kind == "sell_straddle" and legs:
            k = float(legs[0].get("strike") or spot)
            breakevens = [k - credit, k + credit]
        elif len(legs) >= 2:
            puts = [float(lg.get("strike") or 0) for lg in legs if str(lg.get("type")).startswith("P")]
            calls = [float(lg.get("strike") or 0) for lg in legs if str(lg.get("type")).startswith("C")]
            if puts and calls:
                breakevens = [puts[0] - credit, calls[0] + credit]

    elif kind == "buy_straddle":
        debit = -net_cash
        max_loss = debit
        unlimited_profit = True
        if legs:
            k = float(legs[0].get("strike") or spot)
            breakevens = [k - debit, k + debit]

    elif kind == "iron_condor" and len(leg_flows) >= 4:
        credit = net_cash
        strikes = sorted(lf[2] for lf in leg_flows)
        wing = max(strikes[-1] - strikes[-2], strikes[1] - strikes[0])
        max_profit = credit
        max_loss = max(wing - credit, 0.0)

    spot_up = spot * 1.05
    spot_dn = spot * 0.95
    scenarios = {
        "spot_up_5pct_pnl_usd": round(_pnl_at_spot(legs, leg_flows, spot_up), 2),
        "spot_down_5pct_pnl_usd": round(_pnl_at_spot(legs, leg_flows, spot_dn), 2),
    }

    per_contract = {
        "available": True,
        "net_cash_usd": round(net_cash, 2),
        "is_debit": net_cash < 0,
        "max_profit_usd": None if unlimited_profit else (round(max_profit, 2) if max_profit is not None else None),
        "max_loss_usd": None if unlimited_loss else (round(max_loss, 2) if max_loss is not None else None),
        "unlimited_profit": unlimited_profit,
        "unlimited_loss": unlimited_loss,
        "breakevens": [round(b, 2) for b in breakevens if b > 0],
        "reward_risk_ratio": (
            round(max_profit / max_loss, 2)
            if max_profit is not None and max_loss and max_loss > 0
            else None
        ),
        "scenarios": scenarios,
        "margin_required_usd": round(
            sum(
                estimate_option_margin_usd(
                    spot=spot,
                    strike=strike,
                    mark_price_usd=abs(flow),
                    side=side,
                    opt_type=opt_type,
                )
                for flow, opt_type, strike, side in leg_flows
            ),
            2,
        ),
    }

    stop_loss = _stop_loss_for_kind(
        kind,
        spot=spot,
        dte=dte,
        net_cash_usd=net_cash,
        max_loss_usd=max_loss,
        legs=legs,
        leg_flows=leg_flows,
    )

    return {"per_contract": per_contract, "stop_loss": stop_loss}


def _scale_pnl(
    per_contract: dict[str, Any],
    *,
    capital_usd: float,
    options_budget_pct: float,
) -> dict[str, Any]:
    if not per_contract.get("available"):
        return {"available": False}
    margin = float(per_contract.get("margin_required_usd") or 0)
    budget = capital_usd * options_budget_pct
    scale = min(1.0, budget / margin) if margin > 0 else 1.0
    factor = scale  # fractional contracts

    def sc(v: float | None) -> float | None:
        if v is None:
            return None
        return round(v * factor, 2)

    scenarios = per_contract.get("scenarios") or {}
    return {
        "available": True,
        "capital_usd": capital_usd,
        "options_budget_pct": options_budget_pct,
        "options_budget_usd": round(budget, 2),
        "scale_factor": round(factor, 4),
        "net_cash_usd": sc(per_contract.get("net_cash_usd")),
        "max_profit_usd": sc(per_contract.get("max_profit_usd")),
        "max_loss_usd": sc(per_contract.get("max_loss_usd")),
        "margin_required_usd": round(margin * factor, 2),
        "scenarios": {k: sc(v) for k, v in scenarios.items()},
    }


def attach_strategy_pnl(
    strategies: list[dict[str, Any]],
    *,
    spot: float,
    dte: float = 14.0,
    default_iv: float = 0.5,
    strike_report: dict[str, Any] | None = None,
    marks: list[dict[str, Any]] | None = None,
    capital_usd: float = DEFAULT_CAPITAL_USD,
    options_budget_pct: float = DEFAULT_OPTIONS_BUDGET_PCT,
) -> list[dict[str, Any]]:
    """Enrich strategy dicts with per_contract + scaled pnl and stop_loss."""
    if spot <= 0:
        return strategies

    base = str(strategies[0].get("base") if strategies else "BTC")
    price_index = build_price_index(
        base=base,
        spot=spot,
        strike_report=strike_report,
        marks=marks,
        default_iv=default_iv,
        dte=dte,
    )

    out: list[dict[str, Any]] = []
    for strat in strategies:
        s = dict(strat)
        kind = str(s.get("id") or "wait")
        legs = s.get("legs") or []
        if not legs or kind == "wait":
            s["pnl"] = {
                "per_contract": {"available": False, "reason": "无期权腿"},
                "scaled": {"available": False},
                "stop_loss": _stop_loss_for_kind("wait", spot=spot, dte=dte, net_cash_usd=0, max_loss_usd=None, legs=[], leg_flows=[]),
                "disclaimer": _DISCLAIMER_PNL,
            }
            out.append(s)
            continue

        leg_flows: list[tuple[float, str, float, str]] = []
        any_synthetic = False
        for leg in legs:
            prem, syn = _leg_premium_usd(
                leg,
                price_index=price_index,
                spot=spot,
                iv=default_iv,
                dte=dte,
            )
            any_synthetic = any_synthetic or syn
            opt_type = str(leg.get("type") or "C").upper()[:1]
            strike = float(leg.get("strike") or spot)
            side = str(leg.get("side") or "B")
            flow = _leg_cash_flow(prem, side)
            leg_flows.append((flow, opt_type, strike, side))
            leg["premium_usd"] = round(prem, 2)

        computed = _compute_kind_pnl(kind, legs, leg_flows, spot=spot, dte=dte)
        per_contract = computed.get("per_contract") or {}
        if any_synthetic:
            per_contract["pricing_note"] = "部分权利金为 BS 估算"
        scaled = _scale_pnl(per_contract, capital_usd=capital_usd, options_budget_pct=options_budget_pct)
        sl = computed.get("stop_loss") or {}
        if scaled.get("available") and sl.get("premium_stop_usd"):
            scaled["stop_loss_premium_usd"] = round(float(sl["premium_stop_usd"]) * float(scaled.get("scale_factor") or 1), 2)

        s["pnl"] = {
            "per_contract": per_contract,
            "scaled": scaled,
            "stop_loss": sl,
            "disclaimer": _DISCLAIMER_PNL,
        }
        out.append(s)

    return out
