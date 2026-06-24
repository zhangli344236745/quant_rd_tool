"""Option Greeks from Binance EAPI mark and Deribit book summary."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import math
from datetime import UTC, datetime
from typing import Any, Literal

from quant_rd_tool.crypto_options_strike_probs import norm_cdf

from quant_rd_tool.crypto_options_compare import (
    _expiry_date_key,
    _load_venue_expiry_groups,
    _resolve_expiry_date,
    list_common_expiries,
)
from quant_rd_tool.crypto_options_data import fetch_mark_rows, parse_option_symbol
from quant_rd_tool.crypto_options_deribit_data import fetch_book_summary, parse_deribit_instrument
from quant_rd_tool.crypto_options_surface import _parse_iv

_DISCLAIMER = "研究用途。Greeks 来自各交易所 mark 数据，口径可能不同，不构成投资建议。"


def _safe_float(val: Any) -> float | None:
    try:
        if val is None:
            return None
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_analytical_greeks(
    spot: float,
    strike: float,
    *,
    iv: float,
    dte_days: float,
    opt_type: Literal["C", "P"],
    risk_free: float = 0.0,
) -> dict[str, float]:
    """Black-Scholes Greeks (per 1 underlying coin contract)."""
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_days <= 0:
        return {}
    t = dte_days / 365.0
    sig_sqrt = iv * math.sqrt(t)
    if sig_sqrt <= 0:
        return {}
    d1 = (math.log(spot / strike) + (risk_free + 0.5 * iv * iv) * t) / sig_sqrt
    d2 = d1 - sig_sqrt
    pdf = _norm_pdf(d1)
    gamma = pdf / (spot * sig_sqrt)
    vega = spot * pdf * math.sqrt(t)
    if opt_type == "C":
        delta = norm_cdf(d1)
        theta = (
            -spot * pdf * iv / (2.0 * math.sqrt(t))
            - risk_free * strike * math.exp(-risk_free * t) * norm_cdf(d2)
        ) / 365.0
    else:
        delta = norm_cdf(d1) - 1.0
        theta = (
            -spot * pdf * iv / (2.0 * math.sqrt(t))
            + risk_free * strike * math.exp(-risk_free * t) * norm_cdf(-d2)
        ) / 365.0
    return {
        "delta": round(delta, 8),
        "gamma": round(gamma, 10),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
    }


def normalize_greeks(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize delta/gamma/theta/vega/rho from venue-specific payloads."""
    if not raw:
        return {}
    g = raw.get("greeks") if isinstance(raw.get("greeks"), dict) else raw
    out: dict[str, Any] = {}
    for key in ("delta", "gamma", "theta", "vega", "rho"):
        v = _safe_float(g.get(key))
        if v is not None:
            out[key] = round(v, 8)
    return out


def _binance_mark_index(marks: list[dict[str, Any]], base: str) -> dict[str, dict[str, Any]]:
    base_u = base.upper()
    out: dict[str, dict[str, Any]] = {}
    for row in marks:
        sym = str(row.get("symbol") or "")
        meta = parse_option_symbol(sym)
        if not meta or meta["base"] != base_u:
            continue
        iv = _parse_iv(row)
        out[sym] = {
            "symbol": sym,
            "strike": meta["strike"],
            "side": meta["side"],
            "expiry": meta["expiry"],
            "mark_iv": iv,
            "mark_price": _safe_float(row.get("markPrice")),
            "greeks": normalize_greeks(row),
        }
    return out


def _deribit_summary_index(rows: list[dict[str, Any]], base: str) -> dict[str, dict[str, Any]]:
    base_u = base.upper()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("instrument_name") or "")
        meta = parse_deribit_instrument(sym)
        if not meta or meta["base"] != base_u:
            continue
        from quant_rd_tool.crypto_options_deribit_data import normalize_mark_iv

        iv = normalize_mark_iv(row.get("mark_iv"))
        greeks = normalize_greeks(row)
        out[sym] = {
            "symbol": sym,
            "strike": meta["strike"],
            "side": meta["side"],
            "expiry": meta["expiry"],
            "mark_iv": iv,
            "mark_price": _safe_float(row.get("mark_price")),
            "open_interest": row.get("open_interest"),
            "greeks": greeks,
        }
    return out


def _pick_contract(
    index: dict[str, dict[str, Any]],
    *,
    expiry: datetime,
    strike: float,
    side: str,
) -> dict[str, Any] | None:
    date_key = _expiry_date_key(expiry)
    for ent in index.values():
        if _expiry_date_key(ent["expiry"]) != date_key:
            continue
        if abs(float(ent["strike"]) - strike) > 1e-6:
            continue
        if ent.get("side") == side:
            return ent
    return None


def build_greeks_chain(
    base: str,
    *,
    expiry_date: str | None = None,
    n: int = 3,
    min_dte: int = 7,
    client: Any = None,
) -> dict[str, Any]:
    """ATM ±N call/put Greeks on aligned expiry from Binance and Deribit."""
    base_u = base.upper()
    common = list_common_expiries(base_u, min_dte=min_dte, client=client)
    date_key = _resolve_expiry_date(expiry_date, common)
    if not date_key:
        return {
            "base": base_u,
            "available": False,
            "reason": "no common expiry between venues",
            "disclaimer": _DISCLAIMER,
        }

    marks = fetch_mark_rows(client=client)
    b_index = _binance_mark_index(marks, base_u)
    try:
        d_rows = fetch_book_summary(base_u, client=client)
    except Exception as e:
        return {
            "base": base_u,
            "available": False,
            "reason": str(e),
            "disclaimer": _DISCLAIMER,
        }
    d_index = _deribit_summary_index(d_rows, base_u)

    b_grouped, d_grouped, b_spot, d_spot = _load_venue_expiry_groups(
        base_u, min_dte=min_dte, client=client
    )
    b_exp = next(k for k in b_grouped if _expiry_date_key(k) == date_key)
    d_exp = next(k for k in d_grouped if _expiry_date_key(k) == date_key)

    b_strikes = {float(r["strike"]) for r in b_grouped[b_exp]}
    d_strikes = {float(r["strike"]) for r in d_grouped[d_exp]}
    shared = sorted(b_strikes & d_strikes)
    if not shared:
        return {
            "base": base_u,
            "available": False,
            "expiry_date": date_key,
            "reason": "no overlapping strikes",
            "disclaimer": _DISCLAIMER,
        }

    spot = float(b_spot or d_spot or 0)
    atm_k = min(shared, key=lambda k: abs(k - spot)) if spot > 0 else shared[len(shared) // 2]
    idx = shared.index(atm_k)
    lo = max(0, idx - n)
    hi = min(len(shared), idx + n + 1)
    chosen = shared[lo:hi]

    now = datetime.now(UTC)
    dte = (b_exp - now).total_seconds() / 86400.0
    ladder: list[dict[str, Any]] = []
    for k in chosen:
        b_call = _pick_contract(b_index, expiry=b_exp, strike=k, side="C")
        d_call = _pick_contract(d_index, expiry=d_exp, strike=k, side="C")
        b_put = _pick_contract(b_index, expiry=b_exp, strike=k, side="P")
        d_put = _pick_contract(d_index, expiry=d_exp, strike=k, side="P")
        ladder.append(
            {
                "strike": k,
                "moneyness_pct": round((k / spot - 1.0) * 100.0, 2) if spot > 0 else None,
                "call": {
                    "binance": b_call,
                    "deribit": d_call,
                },
                "put": {
                    "binance": b_put,
                    "deribit": d_put,
                },
            }
        )

    atm_entry = next((r for r in ladder if r["strike"] == atm_k), ladder[len(ladder) // 2])

    def _contract_index() -> dict[str, dict[str, Any]]:
        idx: dict[str, dict[str, Any]] = {}
        for side_key, side_char in (("call", "C"), ("put", "P")):
            for row in ladder:
                k = row["strike"]
                for venue in ("binance", "deribit"):
                    ent = (row.get(side_key) or {}).get(venue)
                    if not ent:
                        continue
                    key = f"{venue}:{k}:{side_char}"
                    idx[key] = ent
        return idx

    return {
        "base": base_u,
        "available": True,
        "expiry_date": date_key,
        "binance_expiry": b_exp.isoformat(),
        "deribit_expiry": d_exp.isoformat(),
        "dte": round(dte, 2),
        "spot": b_spot,
        "deribit_spot": d_spot,
        "atm_strike": atm_k,
        "atm_call": atm_entry.get("call"),
        "atm_put": atm_entry.get("put"),
        "rows": ladder,
        "contract_index": _contract_index(),
        "common_expiries": common.get("expiries") or [],
        "disclaimer": _DISCLAIMER,
        "scanned_at": now_iso(),
    }


def lookup_contract_greeks(
    chain: dict[str, Any],
    *,
    strike: float,
    opt_type: str,
    venue: str = "binance",
) -> dict[str, Any] | None:
    """Resolve Greeks for one strike/type from a build_greeks_chain payload."""
    if not chain.get("available"):
        return None
    side = (opt_type or "C").upper()[:1]
    if side not in ("C", "P"):
        side = "C"
    key = f"{venue}:{strike}:{side}"
    idx = chain.get("contract_index") or {}
    ent = idx.get(key)
    if ent:
        return ent
    spot = float(chain.get("spot") or 0)
    iv = None
    for row in chain.get("rows") or []:
        if abs(float(row.get("strike") or 0) - float(strike)) > 1e-6:
            continue
        leg = (row.get("call") if side == "C" else row.get("put")) or {}
        ent = leg.get(venue)
        if ent:
            iv = ent.get("mark_iv")
            break
    if spot <= 0:
        return None
    iv_f = float(iv) if iv else 0.5
    g = bs_analytical_greeks(
        spot,
        float(strike),
        iv=iv_f,
        dte_days=float(chain.get("dte") or 14),
        opt_type=side,  # type: ignore[arg-type]
    )
    return {"strike": strike, "greeks": g, "mark_iv": iv_f, "synthetic": True}
