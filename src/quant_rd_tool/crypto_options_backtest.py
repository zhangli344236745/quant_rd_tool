"""Historical options overlay backtest (BS mark-to-market + IV JSONL)."""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd

from quant_rd_tool.crypto_options_data import load_history
from quant_rd_tool.crypto_options_strike_probs import annualized_realized_vol, norm_cdf
from quant_rd_tool.crypto_zipline_pandas import run_bar_backtest

OptionsOverlayId = Literal[
    "call_overlay",
    "put_hedge",
    "short_straddle_iv",
    "covered_call",
    "long_straddle",
]

OptionsOverlayInput = OptionsOverlayId | Literal["auto"]

_DISCLAIMER = (
    "期权回测为 BS 定价 + 历史 IV 快照近似，未计手续费、滑点与保证金；仅供研究。"
)

def stance_from_final_signal(final_signal: dict[str, Any] | None) -> str:
    sig = final_signal or {}
    pos = str(sig.get("position") or "flat").lower()
    try:
        tgt = float(sig.get("target_pct") or 0)
    except (TypeError, ValueError):
        tgt = 0.0
    if pos == "long" or tgt >= 0.55:
        return "看涨"
    if pos == "short" or tgt <= 0.05:
        return "看跌"
    return "中性"


def resolve_overlay_for_symbol(
    symbol: str,
    *,
    data_dir: str = "data/crypto",
    spot_stance: str = "中性",
    strategy_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build strategy_pack (if needed) and pick overlay structure."""
    from quant_rd_tool.crypto_options_strategies import (
        build_strategy_pack,
        resolve_overlay_from_strategy_pack,
    )

    pack = strategy_pack
    if pack is None:
        from quant_rd_tool.crypto_options_integration import fetch_options_context

        ctx = fetch_options_context(symbol, data_dir=data_dir, persist_snapshot=False)
        if not ctx.get("enabled"):
            return {
                "overlay_id": "call_overlay",
                "fallback": True,
                "skip_reason": None,
                "reason": "期权数据不可用，回退 Call 叠加",
                "headline": "回退",
            }
        pack = build_strategy_pack(
            scan_item=ctx.get("scan_item"),
            strike_report=ctx.get("strike_ladder"),
            spot_stance=spot_stance,
            venue_compare=ctx.get("venue_compare"),
        )
    resolved = resolve_overlay_from_strategy_pack(pack)
    resolved["strategy_pack"] = pack
    return resolved


_DEFAULT_OVERLAY = {
    "options_pct": 0.25,
    "dte_days": 14,
    "iv_percentile_threshold": 80,
    "wing_pct": 0.05,
    "risk_free": 0.0,
    "min_iv": 0.15,
}


def bs_call_price(
    spot: float,
    strike: float,
    *,
    iv: float,
    dte_days: float,
    risk_free: float = 0.0,
) -> float:
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_days <= 0:
        return 0.0
    t = dte_days / 365.0
    sig_sqrt = iv * math.sqrt(t)
    if sig_sqrt <= 0:
        return max(0.0, spot - strike)
    d1 = (math.log(spot / strike) + (risk_free + 0.5 * iv**2) * t) / sig_sqrt
    d2 = d1 - sig_sqrt
    return spot * norm_cdf(d1) - strike * math.exp(-risk_free * t) * norm_cdf(d2)


def bs_put_price(
    spot: float,
    strike: float,
    *,
    iv: float,
    dte_days: float,
    risk_free: float = 0.0,
) -> float:
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_days <= 0:
        return max(0.0, strike - spot)
    t = dte_days / 365.0
    sig_sqrt = iv * math.sqrt(t)
    if sig_sqrt <= 0:
        return max(0.0, strike - spot)
    d1 = (math.log(spot / strike) + (risk_free + 0.5 * iv**2) * t) / sig_sqrt
    d2 = d1 - sig_sqrt
    return strike * math.exp(-risk_free * t) * norm_cdf(-d2) - spot * norm_cdf(-d1)


def _bar_times(df: pd.DataFrame) -> pd.Series:
    if "date" in df.columns:
        return pd.to_datetime(df["date"], utc=True, errors="coerce")
    if "timestamp" in df.columns:
        return pd.to_datetime(df["timestamp"], unit="ms", utc=True, errors="coerce")
    return pd.to_datetime(df.index, utc=True, errors="coerce")


def align_iv_to_bars(
    df: pd.DataFrame,
    iv_history: list[dict[str, Any]],
    *,
    lookback_days: int = 30,
) -> pd.DataFrame:
    """Forward-fill ATM IV onto OHLCV bars; add iv_percentile proxy."""
    times = _bar_times(df)
    out = pd.DataFrame({"bar_time": times})
    if not iv_history:
        out["atm_iv"] = np.nan
        out["iv_percentile"] = np.nan
        return out

    snaps = []
    for row in iv_history:
        ts = row.get("ts")
        iv = row.get("atm_iv")
        if ts is None or iv is None:
            continue
        try:
            snaps.append(
                {
                    "snap_time": pd.Timestamp(ts),
                    "atm_iv": float(iv),
                    "strike": float(row.get("strike") or 0) or None,
                }
            )
        except (TypeError, ValueError):
            continue
    if not snaps:
        out["atm_iv"] = np.nan
        out["iv_percentile"] = np.nan
        return out

    snap_df = pd.DataFrame(snaps).sort_values("snap_time")
    merged = pd.merge_asof(
        out.sort_values("bar_time"),
        snap_df,
        left_on="bar_time",
        right_on="snap_time",
        direction="backward",
    )
    merged = merged.sort_index()
    ivs = merged["atm_iv"].astype(float)
    pct: list[float | None] = []
    for i, t in enumerate(merged["bar_time"]):
        cur = ivs.iloc[i]
        if pd.isna(cur):
            pct.append(None)
            continue
        window = snap_df[snap_df["snap_time"] <= t]["atm_iv"].astype(float)
        if len(window) < 3:
            pct.append(50.0)
            continue
        tail = window.tail(max(lookback_days, 5))
        rank = float((tail <= cur).sum()) / len(tail) * 100.0
        pct.append(round(rank, 1))
    merged["iv_percentile"] = pct
    return merged


def _iv_for_bar(
    iv_row: pd.Series,
    closes: pd.Series,
    i: int,
    *,
    min_iv: float,
) -> float:
    iv = iv_row.get("atm_iv")
    try:
        if iv is not None and not pd.isna(iv) and float(iv) > 0:
            return max(min_iv, float(iv))
    except (TypeError, ValueError):
        pass
    rv = annualized_realized_vol(closes.iloc[: i + 1], 20)
    return max(min_iv, float(rv) if rv else 0.5)


def _atm_strike(spot: float, ref_strike: float | None = None) -> float:
    if ref_strike and ref_strike > 0:
        return ref_strike
    if spot >= 10000:
        step = 1000.0
    elif spot >= 1000:
        step = 100.0
    else:
        step = 10.0
    return round(spot / step) * step


def _targets_from_spot_result(spot_result: dict[str, Any]) -> list[float]:
    curve = spot_result.get("equity_curve") or []
    targets: list[float] = []
    for pt in curve:
        t = pt.get("target")
        targets.append(float(t) if t is not None else 0.0)
    return targets


def run_options_overlay(
    df: pd.DataFrame,
    spot_result: dict[str, Any],
    *,
    symbol: str,
    data_dir: str,
    overlay_id: OptionsOverlayId = "call_overlay",
    params: dict[str, Any] | None = None,
    capital_base: float | None = None,
) -> dict[str, Any]:
    """
    Simulate options leg alongside an existing spot backtest result.
    Returns options metrics + combined equity curve.
    """
    p = {**_DEFAULT_OVERLAY, **(params or {})}
    base = symbol.strip().upper()
    iv_hist = load_history(base, data_dir=data_dir, limit=2000)
    iv_frame = align_iv_to_bars(df, iv_hist)
    work = df.reset_index(drop=True)
    closes = work["close"].astype(float)
    cap = float(capital_base or spot_result.get("capital_base") or 100_000.0)

    spot_curve = spot_result.get("equity_curve") or []
    if len(spot_curve) != len(work):
        raise ValueError("spot equity curve length mismatch with OHLCV bars")

    targets = _targets_from_spot_result(spot_result)
    options_pct = float(p["options_pct"])
    dte_hold = float(p["dte_days"])
    risk_free = float(p["risk_free"])
    min_iv = float(p["min_iv"])
    wing = float(p["wing_pct"])
    iv_thresh = float(p["iv_percentile_threshold"])

    opt_cash = cap * options_pct
    opt_value = opt_cash
    opt_curve: list[dict[str, Any]] = []
    combined_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    position: dict[str, Any] | None = None

    def close_position(i: int, price: float, reason: str) -> None:
        nonlocal opt_value, position
        if not position:
            return
        opt_value = float(position["mtm"])
        trades.append(
            {
                "time": str(spot_curve[i].get("time", "")),
                "side": "close",
                "structure": position["structure"],
                "price": round(price, 4),
                "pnl": round(opt_value - float(position["entry_value"]), 2),
                "reason": reason,
            }
        )
        position = None

    for i in range(len(work)):
        spot_eq = float(spot_curve[i]["value"])
        spot = float(closes.iloc[i])
        tgt = targets[i] if i < len(targets) else 0.0
        iv = _iv_for_bar(iv_frame.iloc[i], closes, i, min_iv=min_iv)
        iv_pct = iv_frame.iloc[i].get("iv_percentile")
        try:
            iv_pct_f = float(iv_pct) if iv_pct is not None and not pd.isna(iv_pct) else 50.0
        except (TypeError, ValueError):
            iv_pct_f = 50.0
        strike = _atm_strike(spot, iv_frame.iloc[i].get("strike"))
        dte = dte_hold

        want: str | None = None
        if overlay_id == "call_overlay" and tgt >= 0.5:
            want = "long_call"
        elif overlay_id == "put_hedge" and tgt >= 0.5:
            want = "long_put"
        elif overlay_id == "covered_call" and tgt >= 0.5:
            want = "covered_call"
        elif overlay_id == "short_straddle_iv" and tgt < 0.5 and iv_pct_f >= iv_thresh:
            want = "short_straddle"
        elif overlay_id == "long_straddle" and tgt < 0.5:
            want = "long_straddle"

        if position and position.get("structure") != want:
            close_position(i, float(position["mtm"]), "signal_change")

        if want and not position:
            entry_val = opt_cash
            if want == "long_call":
                prem = bs_call_price(spot, strike, iv=iv, dte_days=dte, risk_free=risk_free)
                position = {
                    "structure": want,
                    "strike": strike,
                    "entry_spot": spot,
                    "entry_iv": iv,
                    "entry_dte": dte,
                    "contracts_notional": entry_val,
                    "entry_value": entry_val,
                    "mtm": entry_val,
                }
                trades.append(
                    {
                        "time": str(spot_curve[i].get("time", "")),
                        "side": "open",
                        "structure": want,
                        "strike": strike,
                        "premium": round(prem, 4),
                    }
                )
            elif want == "long_put":
                otm_k = strike * (1.0 - wing)
                prem = bs_put_price(spot, otm_k, iv=iv, dte_days=dte, risk_free=risk_free)
                position = {
                    "structure": want,
                    "strike": otm_k,
                    "entry_spot": spot,
                    "entry_iv": iv,
                    "entry_dte": dte,
                    "contracts_notional": entry_val,
                    "entry_value": entry_val,
                    "mtm": entry_val,
                }
                trades.append(
                    {
                        "time": str(spot_curve[i].get("time", "")),
                        "side": "open",
                        "structure": want,
                        "strike": otm_k,
                        "premium": round(prem, 4),
                    }
                )
            elif want == "covered_call":
                call_k = strike * (1.0 + wing)
                call_p = bs_call_price(spot, call_k, iv=iv, dte_days=dte, risk_free=risk_free)
                position = {
                    "structure": want,
                    "strike": call_k,
                    "entry_spot": spot,
                    "entry_iv": iv,
                    "entry_dte": dte,
                    "contracts_notional": entry_val,
                    "entry_value": entry_val,
                    "mtm": entry_val,
                    "short_call_premium": call_p,
                }
                trades.append(
                    {
                        "time": str(spot_curve[i].get("time", "")),
                        "side": "open",
                        "structure": want,
                        "strike": call_k,
                        "premium": round(call_p, 4),
                    }
                )
            elif want == "short_straddle":
                c = bs_call_price(spot, strike, iv=iv, dte_days=dte, risk_free=risk_free)
                pu = bs_put_price(spot, strike, iv=iv, dte_days=dte, risk_free=risk_free)
                position = {
                    "structure": want,
                    "strike": strike,
                    "entry_spot": spot,
                    "entry_iv": iv,
                    "entry_dte": dte,
                    "contracts_notional": entry_val,
                    "entry_value": entry_val,
                    "mtm": entry_val,
                    "short_premium": c + pu,
                }
                trades.append(
                    {
                        "time": str(spot_curve[i].get("time", "")),
                        "side": "open",
                        "structure": want,
                        "strike": strike,
                        "premium": round(c + pu, 4),
                    }
                )
            elif want == "long_straddle":
                c = bs_call_price(spot, strike, iv=iv, dte_days=dte, risk_free=risk_free)
                pu = bs_put_price(spot, strike, iv=iv, dte_days=dte, risk_free=risk_free)
                position = {
                    "structure": want,
                    "strike": strike,
                    "entry_spot": spot,
                    "entry_iv": iv,
                    "entry_dte": dte,
                    "contracts_notional": entry_val,
                    "entry_value": entry_val,
                    "mtm": entry_val,
                    "long_premium": c + pu,
                }
                trades.append(
                    {
                        "time": str(spot_curve[i].get("time", "")),
                        "side": "open",
                        "structure": want,
                        "strike": strike,
                        "premium": round(c + pu, 4),
                    }
                )

        if position:
            elapsed_bars = max(0, i - int(position.get("open_i", i)))
            rem_dte = max(0.5, float(position["entry_dte"]) - elapsed_bars / max(1.0, 24.0 * 4.0))
            if position.get("open_i") is None:
                position["open_i"] = i
            k = float(position["strike"])
            struct = position["structure"]
            if struct == "long_call":
                prem = bs_call_price(spot, k, iv=iv, dte_days=rem_dte, risk_free=risk_free)
                entry_prem = bs_call_price(
                    float(position["entry_spot"]),
                    k,
                    iv=float(position["entry_iv"]),
                    dte_days=float(position["entry_dte"]),
                    risk_free=risk_free,
                )
                position["mtm"] = float(position["contracts_notional"]) * (
                    prem / entry_prem if entry_prem > 1e-9 else 1.0
                )
            elif struct == "long_put":
                prem = bs_put_price(spot, k, iv=iv, dte_days=rem_dte, risk_free=risk_free)
                entry_prem = bs_put_price(
                    float(position["entry_spot"]),
                    k,
                    iv=float(position["entry_iv"]),
                    dte_days=float(position["entry_dte"]),
                    risk_free=risk_free,
                )
                position["mtm"] = float(position["contracts_notional"]) * (
                    prem / entry_prem if entry_prem > 1e-9 else 1.0
                )
            elif struct == "covered_call":
                call_p = bs_call_price(spot, k, iv=iv, dte_days=rem_dte, risk_free=risk_free)
                entry_short = float(position.get("short_call_premium") or 1.0)
                short_pnl = (entry_short - call_p) / entry_short if entry_short > 1e-9 else 0.0
                position["mtm"] = float(position["contracts_notional"]) * (1.0 + short_pnl)
            elif struct == "short_straddle":
                c = bs_call_price(spot, k, iv=iv, dte_days=rem_dte, risk_free=risk_free)
                pu = bs_put_price(spot, k, iv=iv, dte_days=rem_dte, risk_free=risk_free)
                entry_short = float(position.get("short_premium") or 1.0)
                short_pnl = (entry_short - (c + pu)) / entry_short if entry_short > 1e-9 else 0.0
                position["mtm"] = float(position["contracts_notional"]) * (1.0 + short_pnl)
            elif struct == "long_straddle":
                c = bs_call_price(spot, k, iv=iv, dte_days=rem_dte, risk_free=risk_free)
                pu = bs_put_price(spot, k, iv=iv, dte_days=rem_dte, risk_free=risk_free)
                entry_long = float(position.get("long_premium") or 1.0)
                cur_long = c + pu
                position["mtm"] = float(position["contracts_notional"]) * (
                    cur_long / entry_long if entry_long > 1e-9 else 1.0
                )
            opt_value = float(position["mtm"])
        else:
            opt_value = opt_cash

        t_label = str(spot_curve[i].get("time", ""))
        opt_curve.append({"time": t_label, "value": round(opt_value, 2)})
        spot_leg = spot_eq * (1.0 - options_pct)
        combined_curve.append({"time": t_label, "value": round(spot_leg + opt_value, 2)})

    from quant_rd_tool.crypto_zipline_pandas import _metrics

    opt_metrics = _metrics(
        [p["value"] for p in opt_curve],
        cap * options_pct,
        len([t for t in trades if t.get("side") == "open"]),
    )
    combined_metrics = _metrics(
        [p["value"] for p in combined_curve],
        cap,
        (spot_result.get("metrics") or {}).get("trade_count", 0)
        + len([t for t in trades if t.get("side") == "open"]),
    )

    return {
        "enabled": True,
        "overlay_id": overlay_id,
        "symbol": base,
        "params": p,
        "metrics": opt_metrics,
        "equity_curve": opt_curve,
        "trades": trades,
        "combined_metrics": combined_metrics,
        "combined_equity_curve": combined_curve,
        "iv_snapshots_used": len(iv_hist),
        "disclaimer": _DISCLAIMER,
    }


def attach_options_overlay_to_result(
    result: dict[str, Any],
    *,
    symbol: str,
    data_dir: str,
    df: pd.DataFrame,
    overlay_id: OptionsOverlayInput = "call_overlay",
    params: dict[str, Any] | None = None,
    strategy_pack_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        resolved = strategy_pack_selection
        effective_overlay: OptionsOverlayId
        if overlay_id == "auto":
            resolved = resolved or resolve_overlay_for_symbol(
                symbol,
                data_dir=data_dir,
                spot_stance=stance_from_final_signal(result.get("final_signal")),
            )
            picked = resolved.get("overlay_id")
            if not picked:
                result["options_backtest"] = {
                    "enabled": False,
                    "overlay_id": None,
                    "strategy_pack_selection": resolved,
                    "reason": resolved.get("skip_reason"),
                }
                return result
            effective_overlay = picked  # type: ignore[assignment]
        else:
            effective_overlay = overlay_id  # type: ignore[assignment]

        overlay = run_options_overlay(
            df,
            result,
            symbol=symbol,
            data_dir=data_dir,
            overlay_id=effective_overlay,
            params=params,
            capital_base=result.get("capital_base"),
        )
        if resolved:
            overlay["strategy_pack_selection"] = resolved
        result["options_backtest"] = overlay
    except Exception as e:
        result["options_backtest"] = {"enabled": False, "error": str(e)}
    return result


def run_spot_plus_options_strategy(
    df: pd.DataFrame,
    *,
    signal_strategy: str,
    signal_params: dict[str, Any],
    overlay_id: OptionsOverlayInput,
    overlay_params: dict[str, Any] | None,
    capital_base: float,
    symbol: str,
    data_dir: str,
    strategy_pack_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dedicated options-category strategy: spot signal + options overlay in one run."""
    from quant_rd_tool.crypto_zipline_strategies import get_runner, get_strategy

    spec = get_strategy(signal_strategy)
    if not spec:
        raise ValueError(f"Unknown signal strategy: {signal_strategy}")
    runner = get_runner(signal_strategy)
    if not runner:
        raise ValueError(f"No runner for signal strategy: {signal_strategy}")
    sig_params = {**spec["default_params"], **signal_params}
    spot = runner(df, sig_params, capital_base)
    spot["capital_base"] = capital_base

    resolved = strategy_pack_selection
    effective_overlay: OptionsOverlayId
    if overlay_id == "auto":
        resolved = resolved or resolve_overlay_for_symbol(
            symbol,
            data_dir=data_dir,
            spot_stance=stance_from_final_signal(spot.get("final_signal")),
        )
        picked = resolved.get("overlay_id")
        if not picked:
            spot["options_backtest"] = {
                "enabled": False,
                "strategy_pack_selection": resolved,
                "reason": resolved.get("skip_reason"),
            }
            return {
                "engine": "pandas",
                "metrics": spot.get("metrics") or {},
                "equity_curve": spot.get("equity_curve") or [],
                "trades": spot.get("trades") or [],
                "final_signal": spot.get("final_signal"),
                "strategy_params": {
                    "signal_strategy": signal_strategy,
                    "signal_params": sig_params,
                    "overlay_id": "auto",
                },
                "spot_backtest": {
                    "metrics": spot.get("metrics"),
                    "equity_curve": spot.get("equity_curve"),
                },
                "options_backtest": spot["options_backtest"],
                "disclaimer": _DISCLAIMER,
            }
        effective_overlay = picked  # type: ignore[assignment]
    else:
        effective_overlay = overlay_id  # type: ignore[assignment]

    overlay = run_options_overlay(
        df,
        spot,
        symbol=symbol,
        data_dir=data_dir,
        overlay_id=effective_overlay,
        params=overlay_params,
        capital_base=capital_base,
    )
    if resolved:
        overlay["strategy_pack_selection"] = resolved
    return {
        "engine": "pandas",
        "metrics": overlay["combined_metrics"],
        "equity_curve": overlay["combined_equity_curve"],
        "trades": (spot.get("trades") or []) + (overlay.get("trades") or []),
        "final_signal": spot.get("final_signal"),
        "strategy_params": {
            "signal_strategy": signal_strategy,
            "signal_params": sig_params,
            "overlay_id": overlay_id,
            **(overlay_params or {}),
        },
        "spot_backtest": {
            "metrics": spot.get("metrics"),
            "equity_curve": spot.get("equity_curve"),
        },
        "options_backtest": overlay,
        "disclaimer": _DISCLAIMER,
    }
