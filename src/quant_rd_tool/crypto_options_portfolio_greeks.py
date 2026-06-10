"""Portfolio-level Greeks: spot + multi-leg options structures."""

from __future__ import annotations

from typing import Any, Literal

from quant_rd_tool.crypto_options_greeks import (
    build_greeks_chain,
    bs_analytical_greeks,
    lookup_contract_greeks,
)
from quant_rd_tool.crypto_options_portfolio_greeks_history import (
    persist_portfolio_greeks_report,
    portfolio_id_from_bases,
)

Venue = Literal["binance", "deribit"]
ScaleMode = Literal["notional", "margin"]

_DISCLAIMER_NOTIONAL = (
    "组合 Greeks 为研究估算：现货按仓位比例、期权按策略腿等权缩放；"
    "未计合约乘数差异，不构成投资建议。"
)
_DISCLAIMER_MARGIN = (
    "组合 Greeks 按保证金预算缩放：现货按全额、期权按简化保证金模型分配合约数；"
    "与交易所实际保证金可能有偏差，不构成投资建议。"
)

_OVERLAY_LEGS: dict[str, list[dict[str, Any]]] = {
    "call_overlay": [{"side": "B", "type": "C", "atm": True}],
    "put_hedge": [{"side": "B", "type": "P", "otm": True}],
    "covered_call": [
        {"side": "B", "type": "spot"},
        {"side": "S", "type": "C", "otm": True},
    ],
    "short_straddle_iv": [
        {"side": "S", "type": "C", "atm": True},
        {"side": "S", "type": "P", "atm": True},
    ],
    "long_straddle": [
        {"side": "B", "type": "C", "atm": True},
        {"side": "B", "type": "P", "atm": True},
    ],
}


def _sign(side: str) -> float:
    s = (side or "B").upper()
    return -1.0 if s in ("S", "SELL", "SHORT") else 1.0


def _mark_price_usd(ent: dict[str, Any] | None, spot: float) -> float:
    if not ent:
        return max(spot * 0.02, 1.0)
    mp = ent.get("mark_price")
    if mp is None:
        return max(spot * 0.02, 1.0)
    try:
        v = float(mp)
    except (TypeError, ValueError):
        return max(spot * 0.02, 1.0)
    if v <= 0:
        return max(spot * 0.02, 1.0)
    # Coin-denominated premium when value is small vs spot
    if spot > 1000 and v < 1.0:
        return v * spot
    return v


def estimate_option_margin_usd(
    *,
    spot: float,
    strike: float,
    mark_price_usd: float,
    side: str,
    opt_type: str,
) -> float:
    """Rough USD margin per 1 underlying-coin option contract."""
    if spot <= 0:
        return max(mark_price_usd, 1.0)
    if _sign(side) > 0:
        return max(mark_price_usd, spot * 0.005)
    otm = 0.0
    if opt_type.upper().startswith("P"):
        otm = max(0.0, strike - spot)
    else:
        otm = max(0.0, spot - strike)
    return max(0.15 * spot - otm, 0.10 * spot)


def _leg_greeks(
    greeks: dict[str, Any] | None,
    *,
    spot: float,
    strike: float,
    opt_type: str,
    iv: float,
    dte: float,
) -> dict[str, float]:
    if greeks:
        return {k: float(v) for k, v in greeks.items() if v is not None}
    side = opt_type.upper()[:1]
    if side not in ("C", "P"):
        side = "C"
    return bs_analytical_greeks(spot, strike, iv=iv, dte_days=dte, opt_type=side)  # type: ignore[arg-type]


def _strike_for_template(
    tmpl: dict[str, Any],
    *,
    atm_strike: float,
    wing_pct: float,
) -> float | None:
    if tmpl.get("type") == "spot":
        return None
    opt = str(tmpl.get("type") or "C").upper()[:1]
    if tmpl.get("atm"):
        return atm_strike
    if tmpl.get("otm") and opt == "C":
        return round(atm_strike * (1.0 + wing_pct), 2)
    if tmpl.get("otm") and opt == "P":
        return round(atm_strike * (1.0 - wing_pct), 2)
    return float(tmpl.get("strike") or atm_strike)


def legs_from_strategy(
    strategy: dict[str, Any],
    *,
    chain: dict[str, Any],
    spot_pct: float,
    options_pct: float,
    venue: Venue = "binance",
    wing_pct: float = 0.05,
    scale_mode: ScaleMode = "notional",
    capital: float = 100_000.0,
    base: str | None = None,
) -> list[dict[str, Any]]:
    """Expand strategy_pack leg list into weighted Greek rows."""
    spot = float(chain.get("spot") or 0)
    atm = float(chain.get("atm_strike") or spot)
    dte = float(chain.get("dte") or 14)
    raw_legs = strategy.get("legs") or []
    if not raw_legs:
        return []

    opt_legs = [lg for lg in raw_legs if str(lg.get("type") or "").upper() != "SPOT"]
    out: list[dict[str, Any]] = []
    margin_used = 0.0

    if spot_pct > 1e-6 and spot > 0:
        if scale_mode == "margin":
            spot_margin = spot_pct * capital
            coins = spot_margin / spot
            margin_used += spot_margin
            out.append(
                {
                    "label": "现货多头",
                    "kind": "spot",
                    "base": base,
                    "side": "L",
                    "contracts": coins,
                    "margin_usd": spot_margin,
                    "greeks": {"delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0},
                    "contribution": {
                        "delta": coins,
                        "gamma": 0.0,
                        "theta": 0.0,
                        "vega": 0.0,
                    },
                }
            )
        else:
            out.append(
                {
                    "label": "现货多头",
                    "kind": "spot",
                    "base": base,
                    "side": "L",
                    "weight": spot_pct,
                    "greeks": {"delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0},
                    "contribution": {
                        "delta": spot_pct,
                        "gamma": 0.0,
                        "theta": 0.0,
                        "vega": 0.0,
                    },
                }
            )

    if not opt_legs:
        return out

    prepared: list[dict[str, Any]] = []
    unit_margins: list[float] = []
    for lg in opt_legs:
        opt_type = str(lg.get("type") or "C").upper()[:1]
        strike = float(lg.get("strike") or atm)
        ent = lookup_contract_greeks(chain, strike=strike, opt_type=opt_type, venue=venue)
        g = _leg_greeks(
            (ent or {}).get("greeks"),
            spot=spot,
            strike=strike,
            opt_type=opt_type,
            iv=float((ent or {}).get("mark_iv") or 0.5),
            dte=dte,
        )
        mp = _mark_price_usd(ent, spot)
        m = estimate_option_margin_usd(
            spot=spot,
            strike=strike,
            mark_price_usd=mp,
            side=str(lg.get("side") or "B"),
            opt_type=opt_type,
        )
        prepared.append(
            {
                "lg": lg,
                "opt_type": opt_type,
                "strike": strike,
                "ent": ent,
                "g": g,
                "margin_unit": m,
            }
        )
        unit_margins.append(m)

    if scale_mode == "margin":
        options_budget = options_pct * capital
        total_unit_margin = sum(unit_margins) or 1.0
        contract_scale = options_budget / total_unit_margin
        for item, m in zip(prepared, unit_margins):
            lg = item["lg"]
            sign = _sign(str(lg.get("side") or "B"))
            contracts = contract_scale * sign
            leg_margin = abs(contracts) * m
            margin_used += leg_margin
            g = item["g"]
            out.append(
                {
                    "label": f"{lg.get('side')}/{item['opt_type']} K={item['strike']}",
                    "kind": "option",
                    "base": base,
                    "side": lg.get("side"),
                    "type": item["opt_type"],
                    "strike": item["strike"],
                    "symbol": lg.get("symbol"),
                    "contracts": contracts,
                    "margin_usd": leg_margin,
                    "greeks": g,
                    "contribution": {k: contracts * g.get(k, 0.0) for k in ("delta", "gamma", "theta", "vega")},
                    "synthetic": (item["ent"] or {}).get("synthetic", False),
                }
            )
        if out and out[0].get("kind") == "spot":
            out[0]["_portfolio_margin_used"] = margin_used
        elif out:
            out[0]["_portfolio_margin_used"] = margin_used
        return out

    n_opt = max(1, len(opt_legs))
    opt_weight = options_pct / n_opt
    for item in prepared:
        lg = item["lg"]
        sign = _sign(str(lg.get("side") or "B"))
        w = opt_weight * sign
        g = item["g"]
        out.append(
            {
                "label": f"{lg.get('side')}/{item['opt_type']} K={item['strike']}",
                "kind": "option",
                "base": base,
                "side": lg.get("side"),
                "type": item["opt_type"],
                "strike": item["strike"],
                "symbol": lg.get("symbol"),
                "weight": w,
                "greeks": g,
                "contribution": {k: w * g.get(k, 0.0) for k in ("delta", "gamma", "theta", "vega")},
                "synthetic": (item["ent"] or {}).get("synthetic", False),
            }
        )
    return out


def legs_from_overlay(
    overlay_id: str,
    *,
    chain: dict[str, Any],
    spot_pct: float,
    options_pct: float,
    venue: Venue = "binance",
    wing_pct: float = 0.05,
    scale_mode: ScaleMode = "notional",
    capital: float = 100_000.0,
    base: str | None = None,
) -> list[dict[str, Any]]:
    tmpl_legs = _OVERLAY_LEGS.get(overlay_id, [])
    if not tmpl_legs:
        return []
    atm = float(chain.get("atm_strike") or chain.get("spot") or 0)
    expanded = []
    for t in tmpl_legs:
        if t.get("type") == "spot":
            expanded.append({"side": "B", "type": "spot"})
            continue
        k = _strike_for_template(t, atm_strike=atm, wing_pct=wing_pct)
        expanded.append(
            {
                "side": "S" if t.get("side") == "S" else "B",
                "type": t.get("type"),
                "strike": k,
            }
        )
    return legs_from_strategy(
        {"legs": expanded},
        chain=chain,
        spot_pct=spot_pct,
        options_pct=options_pct,
        venue=venue,
        wing_pct=wing_pct,
        scale_mode=scale_mode,
        capital=capital,
        base=base,
    )


def _margin_used_from_legs(legs: list[dict[str, Any]], *, capital: float, spot_pct: float, options_pct: float, scale_mode: ScaleMode) -> float:
    explicit = sum(float(lg.get("margin_usd") or 0) for lg in legs)
    if explicit > 0:
        return explicit
    if scale_mode == "notional":
        return capital * (spot_pct + options_pct)
    return capital * (spot_pct + options_pct)


def aggregate_portfolio_greeks(
    legs: list[dict[str, Any]],
    *,
    spot: float,
    capital: float = 100_000.0,
    scale_mode: ScaleMode = "notional",
    spot_pct: float = 0.0,
    options_pct: float = 0.0,
) -> dict[str, Any]:
    """Sum leg contributions and derive risk proxies."""
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        contrib = leg.get("contribution") or {}
        for k in totals:
            totals[k] += float(contrib.get(k) or 0.0)

    delta_coins = totals["delta"]
    delta_usd = delta_coins * spot if spot > 0 else 0.0
    margin_used = _margin_used_from_legs(
        legs, capital=capital, spot_pct=spot_pct, options_pct=options_pct, scale_mode=scale_mode
    )
    notional = capital
    spot_shock = 0.05 * spot if spot > 0 else 0.0
    pnl_spot_up = delta_coins * spot_shock + 0.5 * totals["gamma"] * (spot_shock**2)
    pnl_theta_1d = totals["theta"]
    pnl_iv_up = totals["vega"] * 0.01

    alerts: list[str] = []
    delta_pct = abs(delta_usd) / notional * 100 if notional > 0 else 0.0
    if delta_pct > 85:
        alerts.append(f"净 Delta 名义敞口偏高（≈{delta_pct:.0f}% 资金）。")
    elif scale_mode == "notional" and abs(delta_coins) > 0.85:
        alerts.append(f"净 Delta 偏高（≈{delta_coins:.2f} 币），方向敞口大。")
    if totals["theta"] < -50 and notional > 0:
        alerts.append("Theta 为负且绝对值较大，持仓每日时间损耗显著。")
    if totals["vega"] < -100:
        alerts.append("净 Vega 为负，IV 上升将拖累组合。")
    elif totals["vega"] > 100:
        alerts.append("净 Vega 为正，IV 下降将拖累组合。")
    if abs(totals["gamma"]) > 1e-4:
        alerts.append("Gamma 暴露非零，价格大幅波动时 Delta 会快速变化。")
    if scale_mode == "margin" and margin_used > capital * 1.01:
        alerts.append(f"估算保证金 {margin_used:,.0f} 超过资金预算 {capital:,.0f}。")

    risk_level = "中"
    if len(alerts) >= 3 or delta_pct > 120:
        risk_level = "高"
    elif not alerts:
        risk_level = "低"

    return {
        "net": {k: round(v, 8) for k, v in totals.items()},
        "delta_coins": round(delta_coins, 6),
        "delta_usd": round(delta_usd, 2),
        "delta_notional_pct": round(delta_pct, 2) if notional > 0 else None,
        "hedge_coins": round(-delta_coins, 6) if spot > 0 else None,
        "margin_used_usd": round(margin_used, 2),
        "margin_utilization_pct": round(margin_used / capital * 100, 2) if capital > 0 else None,
        "scenarios": {
            "spot_up_5pct_pnl": round(pnl_spot_up, 2),
            "theta_1d_pnl": round(pnl_theta_1d, 2),
            "iv_up_1pt_pnl": round(pnl_iv_up, 2),
        },
        "alerts": alerts,
        "risk_level": risk_level,
    }


def aggregate_multi_portfolio_greeks(
    constituents: list[dict[str, Any]],
    *,
    capital: float = 100_000.0,
) -> dict[str, Any]:
    """Aggregate USD-normalized Greeks across multiple bases."""
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    delta_usd = 0.0
    margin_used = 0.0
    alerts: list[str] = []

    for c in constituents:
        if not c.get("available"):
            continue
        spot = float(c.get("spot") or 0)
        summary = c.get("summary") or {}
        net = summary.get("net") or {}
        delta_usd += float(summary.get("delta_usd") or 0)
        margin_used += float(summary.get("margin_used_usd") or 0)
        totals["theta"] += float(net.get("theta") or 0)
        totals["vega"] += float(net.get("vega") or 0)
        if spot > 0:
            totals["gamma"] += float(net.get("gamma") or 0) * (spot**2) / 100.0
        for msg in summary.get("alerts") or []:
            base = c.get("base", "?")
            alerts.append(f"[{base}] {msg}")

    delta_pct = abs(delta_usd) / capital * 100 if capital > 0 else 0.0
    risk_level = "中"
    if len(alerts) >= 4 or delta_pct > 100:
        risk_level = "高"
    elif not alerts:
        risk_level = "低"

    return {
        "net": {k: round(v, 4) for k, v in totals.items()},
        "delta_usd": round(delta_usd, 2),
        "delta_notional_pct": round(delta_pct, 2) if capital > 0 else None,
        "margin_used_usd": round(margin_used, 2),
        "margin_utilization_pct": round(margin_used / capital * 100, 2) if capital > 0 else None,
        "gamma_usd_scale_note": "多币种 Gamma 为各资产 Γ×S²/100 之和（研究近似）",
        "alerts": alerts[:8],
        "risk_level": risk_level,
    }


def build_portfolio_greeks_report(
    base: str,
    *,
    spot_pct: float = 0.75,
    options_pct: float = 0.25,
    overlay_id: str | None = None,
    strategy: dict[str, Any] | None = None,
    strategy_index: int = 0,
    strategy_pack: dict[str, Any] | None = None,
    venue: Venue = "binance",
    capital: float = 100_000.0,
    expiry_date: str | None = None,
    wing_pct: float = 0.05,
    scale_mode: ScaleMode = "notional",
    client: Any = None,
    persist: bool = False,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    """Build portfolio Greeks for spot + options legs."""
    base_u = base.upper()
    chain = build_greeks_chain(base_u, expiry_date=expiry_date, n=3, client=client)
    disclaimer = _DISCLAIMER_MARGIN if scale_mode == "margin" else _DISCLAIMER_NOTIONAL
    if not chain.get("available"):
        return {
            "base": base_u,
            "available": False,
            "reason": chain.get("reason", "greeks chain unavailable"),
            "disclaimer": disclaimer,
        }

    strat = strategy
    if strat is None and strategy_pack:
        strats = strategy_pack.get("strategies") or []
        if strats:
            idx = min(max(0, strategy_index), len(strats) - 1)
            strat = strats[idx]

    common_kw = dict(
        chain=chain,
        spot_pct=spot_pct,
        options_pct=options_pct,
        venue=venue,
        wing_pct=wing_pct,
        scale_mode=scale_mode,
        capital=capital,
        base=base_u,
    )

    if strat and strat.get("legs") is not None:
        legs = legs_from_strategy(strat, **common_kw)
        source = {"type": "strategy_pack", "name": strat.get("name"), "id": strat.get("id")}
    elif overlay_id:
        legs = legs_from_overlay(overlay_id, **common_kw)
        source = {"type": "overlay", "overlay_id": overlay_id}
    else:
        legs = legs_from_overlay("call_overlay", **common_kw)
        source = {"type": "default", "overlay_id": "call_overlay"}

    spot = float(chain.get("spot") or 0)
    summary = aggregate_portfolio_greeks(
        legs,
        spot=spot,
        capital=capital,
        scale_mode=scale_mode,
        spot_pct=spot_pct,
        options_pct=options_pct,
    )
    report = {
        "base": base_u,
        "bases": [base_u],
        "portfolio_id": base_u,
        "available": True,
        "multi": False,
        "spot": spot,
        "expiry_date": chain.get("expiry_date"),
        "dte": chain.get("dte"),
        "atm_strike": chain.get("atm_strike"),
        "venue": venue,
        "scale_mode": scale_mode,
        "allocation": {"spot_pct": spot_pct, "options_pct": options_pct, "capital": capital},
        "source": source,
        "legs": legs,
        "summary": summary,
        "disclaimer": disclaimer,
    }
    if persist:
        persist_portfolio_greeks_report(report, data_dir=data_dir)
    return report


def _parse_position_weights(
    bases: list[str],
    weights: list[float] | None,
) -> list[float]:
    n = len(bases)
    if not weights:
        return [1.0 / n] * n if n else []
    if len(weights) != n:
        raise ValueError("weights length must match bases")
    total = sum(weights)
    if total <= 0:
        raise ValueError("weights must sum to a positive value")
    return [w / total for w in weights]


def build_multi_portfolio_greeks_report(
    positions: list[dict[str, Any]],
    *,
    capital: float = 100_000.0,
    venue: Venue = "binance",
    scale_mode: ScaleMode = "notional",
    use_strategy_pack: bool = False,
    spot_stance: str = "中性",
    persist: bool = False,
    data_dir: str = "data/crypto",
    client: Any = None,
) -> dict[str, Any]:
    """Build aggregated portfolio Greeks across multiple bases."""
    if not positions:
        return {"available": False, "reason": "no positions", "multi": True}

    constituents: list[dict[str, Any]] = []
    bases: list[str] = []

    for pos in positions:
        base_u = str(pos.get("base") or "").upper()
        if not base_u:
            continue
        weight = float(pos.get("weight_pct") or pos.get("weight") or 1.0)
        pos_capital = capital * weight
        pack = pos.get("strategy_pack")
        if use_strategy_pack and pack is None:
            from quant_rd_tool.crypto_options_strategies import build_strategy_pack
            from quant_rd_tool.crypto_options_vol_scan import run_volatility_scan

            scan = run_volatility_scan(symbols=[base_u], persist_snapshot=False)
            item = next((i for i in scan.get("items") or [] if i.get("base") == base_u), None)
            if item:
                pack = build_strategy_pack(scan_item=item, spot_stance=spot_stance)

        sub = build_portfolio_greeks_report(
            base_u,
            spot_pct=float(pos.get("spot_pct", 0.75)),
            options_pct=float(pos.get("options_pct", 0.25)),
            overlay_id=pos.get("overlay_id"),
            strategy_pack=pack if isinstance(pack, dict) else None,
            strategy_index=int(pos.get("strategy_index") or 0),
            venue=venue,
            capital=pos_capital,
            expiry_date=pos.get("expiry_date"),
            scale_mode=scale_mode,
            client=client,
            persist=False,
        )
        sub["weight_pct"] = round(weight * 100, 2)
        constituents.append(sub)
        bases.append(base_u)

    if not constituents:
        return {"available": False, "reason": "no valid bases", "multi": True}

    available_subs = [c for c in constituents if c.get("available")]
    if not available_subs:
        return {
            "available": False,
            "multi": True,
            "bases": bases,
            "constituents": constituents,
            "reason": "all constituents unavailable",
        }

    summary = aggregate_multi_portfolio_greeks(available_subs, capital=capital)
    pid = portfolio_id_from_bases(bases)
    disclaimer = _DISCLAIMER_MARGIN if scale_mode == "margin" else _DISCLAIMER_NOTIONAL

    report = {
        "available": True,
        "multi": True,
        "bases": bases,
        "portfolio_id": pid,
        "scale_mode": scale_mode,
        "allocation": {"capital": capital},
        "constituents": constituents,
        "summary": summary,
        "disclaimer": disclaimer,
    }
    if persist:
        persist_portfolio_greeks_report(report, data_dir=data_dir)
    return report


def build_multi_from_lists(
    bases: list[str],
    *,
    weights: list[float] | None = None,
    capital: float = 100_000.0,
    spot_pct: float = 0.75,
    options_pct: float = 0.25,
    overlay_id: str | None = None,
    venue: Venue = "binance",
    scale_mode: ScaleMode = "notional",
    use_strategy_pack: bool = False,
    spot_stance: str = "中性",
    persist: bool = False,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    w = _parse_position_weights(bases, weights)
    positions = [
        {
            "base": b,
            "weight_pct": wt,
            "spot_pct": spot_pct,
            "options_pct": options_pct,
            "overlay_id": overlay_id,
        }
        for b, wt in zip(bases, w)
    ]
    return build_multi_portfolio_greeks_report(
        positions,
        capital=capital,
        venue=venue,
        scale_mode=scale_mode,
        use_strategy_pack=use_strategy_pack,
        spot_stance=spot_stance,
        persist=persist,
        data_dir=data_dir,
    )


def attach_portfolio_greeks_to_result(
    result: dict[str, Any],
    *,
    symbol: str,
    capital: float | None = None,
) -> dict[str, Any]:
    """Attach portfolio_greeks to a zipline lab result using backtest context."""
    cap = float(capital or result.get("capital_base") or 100_000.0)
    sig = result.get("final_signal") or {}
    try:
        spot_pct = float(sig.get("target_pct") if sig.get("target_pct") is not None else 0.75)
    except (TypeError, ValueError):
        spot_pct = 0.75

    opt_bt = result.get("options_backtest") or {}
    params = opt_bt.get("params") or {}
    selection = opt_bt.get("strategy_pack_selection") or {}
    overlay_id = opt_bt.get("overlay_id") or selection.get("overlay_id")
    pack = selection.get("strategy_pack")
    scale_mode: ScaleMode = str(params.get("scale_mode") or "margin")  # type: ignore[assignment]
    if scale_mode not in ("notional", "margin"):
        scale_mode = "margin"

    if not overlay_id and not pack:
        ctx = result.get("options_context") or {}
        pack = (ctx.get("strategy_pack") if isinstance(ctx, dict) else None) or pack

    if opt_bt.get("enabled"):
        options_pct = float(params.get("options_pct") or 0.25)
    elif pack:
        options_pct = 0.25
    else:
        options_pct = 0.0
    if spot_pct + options_pct > 1.0:
        spot_pct = max(0.0, 1.0 - options_pct)

    try:
        report = build_portfolio_greeks_report(
            symbol,
            spot_pct=spot_pct,
            options_pct=options_pct,
            overlay_id=str(overlay_id) if overlay_id else None,
            strategy_pack=pack if isinstance(pack, dict) else None,
            capital=cap,
            scale_mode=scale_mode,
        )
        result["portfolio_greeks"] = report
    except Exception as e:
        result["portfolio_greeks"] = {"available": False, "error": str(e)}
    return result
