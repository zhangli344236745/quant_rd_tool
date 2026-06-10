"""IV term structure, expiry list, and skew from Binance EAPI marks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from quant_rd_tool.crypto_options_data import (
    fetch_index_price,
    fetch_mark_rows,
    parse_option_symbol,
    pick_atm_contract,
)

_DISCLAIMER = "研究用途。期限结构与偏斜基于 Binance mark IV，不构成投资建议。"


def _parse_iv(row: dict[str, Any]) -> float | None:
    raw = row.get("markIV") or row.get("askIV") or row.get("bidIV")
    try:
        iv = float(raw)
    except (TypeError, ValueError):
        return None
    if iv <= 0 or iv > 5:
        return None
    return iv


def _group_marks_by_expiry(
    marks: list[dict[str, Any]],
    base: str,
    *,
    min_dte: float = 7,
) -> dict[datetime, list[dict[str, Any]]]:
    """Group parsed mark rows by expiry datetime."""
    base_u = base.upper()
    now = datetime.now(UTC)
    grouped: dict[datetime, list[dict[str, Any]]] = {}
    for row in marks:
        sym = str(row.get("symbol") or "")
        meta = parse_option_symbol(sym)
        if not meta or meta["base"] != base_u:
            continue
        iv = _parse_iv(row)
        if iv is None:
            continue
        expiry = meta["expiry"]
        dte = (expiry - now).total_seconds() / 86400.0
        if dte < min_dte:
            continue
        ent = {
            **meta,
            "mark_iv": iv,
            "mark_price": row.get("markPrice"),
            "dte": round(dte, 2),
        }
        grouped.setdefault(expiry, []).append(ent)
    return grouped


def _atm_iv_for_expiry(rows: list[dict[str, Any]], spot: float) -> dict[str, Any] | None:
    if not rows:
        return None
    calls = [r for r in rows if r.get("side") == "C"]
    pool = calls if calls else rows
    best = min(pool, key=lambda r: abs(float(r["strike"]) - spot))
    return {
        "strike": float(best["strike"]),
        "atm_iv": round(float(best["mark_iv"]), 6),
        "symbol": best.get("symbol"),
        "side": best.get("side"),
        "dte": best.get("dte"),
    }


def list_expiries(
    base: str,
    *,
    min_dte: int = 7,
    client: Any = None,
) -> dict[str, Any]:
    """Available option expiries for an underlying with ATM IV snapshot."""
    base_u = base.upper()
    marks = fetch_mark_rows(client=client)
    spot = fetch_index_price(base_u, client=client)
    if spot is None:
        raise ValueError(f"index price unavailable for {base_u}")

    grouped = _group_marks_by_expiry(marks, base_u, min_dte=float(min_dte))
    expiries: list[dict[str, Any]] = []
    for expiry in sorted(grouped.keys()):
        rows = grouped[expiry]
        atm = _atm_iv_for_expiry(rows, spot)
        if not atm:
            continue
        expiries.append(
            {
                "expiry": expiry.isoformat(),
                "dte": atm.get("dte"),
                "atm_strike": atm.get("strike"),
                "atm_iv": atm.get("atm_iv"),
                "contract": atm.get("symbol"),
                "strike_count": len({r["strike"] for r in rows}),
            }
        )

    default_expiry = None
    atm_pick = pick_atm_contract(marks, base_u, spot, min_days=min_dte)
    if atm_pick:
        default_expiry = atm_pick.get("expiry")

    return {
        "base": base_u,
        "spot": round(spot, 4),
        "expiries": expiries,
        "default_expiry": default_expiry,
        "disclaimer": _DISCLAIMER,
    }


def build_term_structure(
    base: str,
    *,
    min_dte: int = 7,
    client: Any = None,
) -> dict[str, Any]:
    """ATM IV across expiries — term structure curve."""
    base_u = base.upper()
    marks = fetch_mark_rows(client=client)
    spot = fetch_index_price(base_u, client=client)
    if spot is None:
        raise ValueError(f"index price unavailable for {base_u}")

    grouped = _group_marks_by_expiry(marks, base_u, min_dte=float(min_dte))
    points: list[dict[str, Any]] = []
    for expiry in sorted(grouped.keys()):
        atm = _atm_iv_for_expiry(grouped[expiry], spot)
        if not atm:
            continue
        points.append(
            {
                "expiry": expiry.isoformat(),
                "dte": atm.get("dte"),
                "atm_strike": atm.get("strike"),
                "atm_iv": atm.get("atm_iv"),
                "contract": atm.get("symbol"),
            }
        )

    slope_note = None
    if len(points) >= 2:
        front = points[0]
        back = points[-1]
        if front.get("atm_iv") and back.get("atm_iv"):
            diff = float(back["atm_iv"]) - float(front["atm_iv"])
            if diff > 0.03:
                slope_note = "contango（远月 IV 高于近月）"
            elif diff < -0.03:
                slope_note = "backwardation（近月 IV 高于远月）"
            else:
                slope_note = "期限结构较平坦"

    return {
        "base": base_u,
        "spot": round(spot, 4),
        "points": points,
        "slope_note": slope_note,
        "disclaimer": _DISCLAIMER,
    }


def build_iv_skew(
    base: str,
    *,
    expiry_iso: str | None = None,
    min_dte: int = 7,
    client: Any = None,
) -> dict[str, Any]:
    """Volatility smile: strike vs mark IV for one expiry."""
    base_u = base.upper()
    marks = fetch_mark_rows(client=client)
    spot = fetch_index_price(base_u, client=client)
    if spot is None:
        raise ValueError(f"index price unavailable for {base_u}")

    grouped = _group_marks_by_expiry(marks, base_u, min_dte=float(min_dte))
    if not grouped:
        return {
            "base": base_u,
            "spot": round(spot, 4),
            "expiry": None,
            "points": [],
            "warnings": ["no expiries with sufficient DTE"],
            "disclaimer": _DISCLAIMER,
        }

    expiry_dt: datetime | None = None
    if expiry_iso:
        expiry_dt = datetime.fromisoformat(expiry_iso.replace("Z", "+00:00"))
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=UTC)
        if expiry_dt not in grouped:
            # match by date
            match = next((e for e in grouped if e.date() == expiry_dt.date()), None)
            expiry_dt = match
    else:
        atm_pick = pick_atm_contract(marks, base_u, spot, min_days=min_dte)
        if atm_pick:
            exp_raw = atm_pick.get("expiry")
            if exp_raw:
                expiry_dt = datetime.fromisoformat(str(exp_raw).replace("Z", "+00:00"))
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=UTC)
                if expiry_dt not in grouped:
                    expiry_dt = next(
                        (e for e in grouped if e.date() == expiry_dt.date()),
                        sorted(grouped.keys())[0],
                    )
        else:
            expiry_dt = sorted(grouped.keys())[0]

    if expiry_dt is None or expiry_dt not in grouped:
        return {
            "base": base_u,
            "spot": round(spot, 4),
            "expiry": expiry_iso,
            "points": [],
            "warnings": ["expiry not found in marks"],
            "disclaimer": _DISCLAIMER,
        }

    rows = grouped[expiry_dt]
    by_strike: dict[float, dict[str, Any]] = {}
    for r in rows:
        k = float(r["strike"])
        side = r.get("side")
        prev = by_strike.get(k)
        ent = {
            "strike": k,
            "moneyness_pct": round((k / spot - 1.0) * 100.0, 2),
            "call_iv": None,
            "put_iv": None,
            "mark_iv": float(r["mark_iv"]),
            "call_symbol": None,
            "put_symbol": None,
        }
        if prev:
            ent = {**prev}
        if side == "C":
            ent["call_iv"] = round(float(r["mark_iv"]), 6)
            ent["call_symbol"] = r.get("symbol")
        elif side == "P":
            ent["put_iv"] = round(float(r["mark_iv"]), 6)
            ent["put_symbol"] = r.get("symbol")
        if ent.get("call_iv") and ent.get("put_iv"):
            ent["mark_iv"] = round((ent["call_iv"] + ent["put_iv"]) / 2.0, 6)
        by_strike[k] = ent

    points = [by_strike[k] for k in sorted(by_strike.keys())]
    atm_k = min(by_strike.keys(), key=lambda k: abs(k - spot))
    skew_25d = None
    otm_puts = [p for p in points if p["strike"] < atm_k]
    otm_calls = [p for p in points if p["strike"] > atm_k]
    if otm_puts and otm_calls:
        put_iv = otm_puts[-1].get("put_iv") or otm_puts[-1].get("mark_iv")
        call_iv = otm_calls[0].get("call_iv") or otm_calls[0].get("mark_iv")
        atm_iv = by_strike[atm_k].get("mark_iv")
        if put_iv and call_iv and atm_iv:
            skew_25d = round((float(put_iv) + float(call_iv)) / 2.0 - float(atm_iv), 4)

    dte = (expiry_dt - datetime.now(UTC)).total_seconds() / 86400.0
    return {
        "base": base_u,
        "spot": round(spot, 4),
        "expiry": expiry_dt.isoformat(),
        "dte": round(dte, 2),
        "atm_strike": atm_k,
        "skew_25d_proxy": skew_25d,
        "points": points,
        "warnings": [],
        "disclaimer": _DISCLAIMER,
    }
