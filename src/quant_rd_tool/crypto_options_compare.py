"""Cross-venue options IV comparison: Binance EAPI vs Deribit."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import time
from datetime import UTC, datetime
from typing import Any, Literal

from quant_rd_tool.crypto_options_data import (
    fetch_atm_iv_snapshot as binance_atm_snapshot,
    fetch_index_price as binance_index,
    fetch_mark_rows,
)
from quant_rd_tool.crypto_options_deribit_data import (
    _rows_to_candidates,
    fetch_atm_iv_snapshot as deribit_atm_snapshot,
    fetch_book_summary,
    fetch_index_price as deribit_index,
)
from quant_rd_tool.crypto_options_surface import (
    _atm_iv_for_expiry,
    _group_marks_by_expiry,
    build_term_structure as binance_term_structure,
)
from quant_rd_tool.crypto_options_vol_scan import DEFAULT_SYMBOLS

RicherVenue = Literal["binance", "deribit", "neutral", "unavailable"]

_COMPARE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DISCLAIMER = (
    "跨所 IV 对比基于各交易所 mark IV 与指数价，到期日/合约结构可能不同，仅供研究。"
)

_SPREAD_HOT_PP = 5.0
_SPREAD_ELEVATED_PP = 2.5
_DEFAULT_TARGET_DTE = 30


def _expiry_date_key(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.date().isoformat()


def _parse_expiry(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def _strike_iv_map(
    rows: list[dict[str, Any]],
    *,
    prefer_call: bool = True,
) -> dict[float, dict[str, Any]]:
    """Map strike -> best IV row (prefer call) for one expiry."""
    by_strike: dict[float, dict[str, Any]] = {}
    for r in rows:
        try:
            k = float(r["strike"])
            iv = float(r.get("mark_iv") or r.get("iv"))
        except (TypeError, ValueError, KeyError):
            continue
        if iv <= 0:
            continue
        side = r.get("side")
        symbol = r.get("symbol") or r.get("instrument_name")
        prev = by_strike.get(k)
        if prev is None or (prefer_call and side == "C" and prev.get("side") != "C"):
            by_strike[k] = {
                "strike": k,
                "iv": round(iv, 6),
                "symbol": symbol,
                "side": side,
            }
    return by_strike


def _deribit_grouped_by_expiry(
    base: str,
    *,
    min_dte: float = 7,
    client: Any = None,
) -> dict[datetime, list[dict[str, Any]]]:
    idx = deribit_index(base, client=client)
    if idx is None:
        return {}
    try:
        summary = fetch_book_summary(base, client=client)
    except Exception:
        return {}
    grouped: dict[datetime, list[dict[str, Any]]] = {}
    for c in _rows_to_candidates(summary, base, idx, min_days=int(min_dte)):
        grouped.setdefault(c["expiry"], []).append(c)
    return grouped


def _load_venue_expiry_groups(
    base: str,
    *,
    min_dte: int = 7,
    client: Any = None,
) -> tuple[dict[datetime, list[dict[str, Any]]], dict[datetime, list[dict[str, Any]]], float | None, float | None]:
    marks = fetch_mark_rows(client=client)
    b_spot = binance_index(base, client=client)
    b_grouped = _group_marks_by_expiry(marks, base, min_dte=float(min_dte))
    d_grouped = _deribit_grouped_by_expiry(base, min_dte=float(min_dte), client=client)
    d_spot = deribit_index(base, client=client)
    return b_grouped, d_grouped, b_spot, d_spot


def list_common_expiries(
    base: str,
    *,
    min_dte: int = 7,
    client: Any = None,
) -> dict[str, Any]:
    """Calendar dates where both venues list options with mark IV."""
    base_u = base.upper()
    b_grouped, d_grouped, b_spot, d_spot = _load_venue_expiry_groups(
        base_u, min_dte=min_dte, client=client
    )
    b_by_date = {_expiry_date_key(k): k for k in b_grouped}
    d_by_date = {_expiry_date_key(k): k for k in d_grouped}
    common_dates = sorted(set(b_by_date) & set(d_by_date))
    now = datetime.now(UTC)
    spot = b_spot or d_spot or 0.0
    expiries: list[dict[str, Any]] = []
    for date_key in common_dates:
        b_exp = b_by_date[date_key]
        d_exp = d_by_date[date_key]
        b_rows = b_grouped[b_exp]
        d_rows = d_grouped[d_exp]
        b_atm = _atm_iv_for_expiry(b_rows, spot) if spot else None
        d_atm = _atm_iv_for_expiry(
            [{"strike": r["strike"], "mark_iv": r["iv"], "side": r.get("side"), "symbol": r.get("symbol")} for r in d_rows],
            d_spot or spot,
        ) if (d_spot or spot) else None
        dte = (b_exp - now).total_seconds() / 86400.0
        spread_pp = None
        if b_atm and d_atm:
            spread_pp = round((float(b_atm["atm_iv"]) - float(d_atm["atm_iv"])) * 100.0, 2)
        expiries.append(
            {
                "expiry_date": date_key,
                "binance_expiry": b_exp.isoformat(),
                "deribit_expiry": d_exp.isoformat(),
                "dte": round(dte, 2),
                "binance_atm_iv": b_atm.get("atm_iv") if b_atm else None,
                "deribit_atm_iv": d_atm.get("atm_iv") if d_atm else None,
                "atm_iv_spread_pp": spread_pp,
                "common_strikes": len(set(_strike_iv_map(b_rows)) & set(_strike_iv_map(d_rows))),
            }
        )

    default_date = None
    if expiries:
        default_date = min(expiries, key=lambda e: abs(float(e["dte"]) - _DEFAULT_TARGET_DTE))["expiry_date"]

    return {
        "base": base_u,
        "binance_spot": b_spot,
        "deribit_spot": d_spot,
        "expiries": expiries,
        "default_expiry_date": default_date,
        "disclaimer": _DISCLAIMER,
    }


def _resolve_expiry_date(
    expiry_date: str | None,
    common: dict[str, Any],
) -> str | None:
    if expiry_date:
        key = expiry_date[:10]
        dates = {e["expiry_date"] for e in common.get("expiries") or []}
        return key if key in dates else None
    return common.get("default_expiry_date")


def build_aligned_expiry_compare(
    base: str,
    *,
    expiry_date: str | None = None,
    n: int = 5,
    min_dte: int = 7,
    client: Any = None,
) -> dict[str, Any]:
    """
    Compare Binance vs Deribit on the **same calendar expiry** and **same strikes**.
    """
    base_u = base.upper()
    common = list_common_expiries(base_u, min_dte=min_dte, client=client)
    date_key = _resolve_expiry_date(expiry_date, common)
    if not date_key:
        return {
            "base": base_u,
            "available": False,
            "reason": "no common expiry between Binance and Deribit",
            "common_expiries": common.get("expiries") or [],
            "disclaimer": _DISCLAIMER,
        }

    b_grouped, d_grouped, b_spot, d_spot = _load_venue_expiry_groups(
        base_u, min_dte=min_dte, client=client
    )
    b_exp = next(k for k in b_grouped if _expiry_date_key(k) == date_key)
    d_exp = next(k for k in d_grouped if _expiry_date_key(k) == date_key)
    b_rows = b_grouped[b_exp]
    d_rows = d_grouped[d_exp]

    b_map = _strike_iv_map(b_rows)
    d_map = {
        k: {"strike": k, "iv": v["iv"], "symbol": v.get("symbol"), "side": v.get("side")}
        for k, v in _strike_iv_map(
            [
                {
                    "strike": r["strike"],
                    "mark_iv": r["iv"],
                    "side": r.get("side"),
                    "symbol": r.get("symbol"),
                }
                for r in d_rows
            ]
        ).items()
    }
    shared = sorted(set(b_map) & set(d_map))
    if not shared:
        return {
            "base": base_u,
            "available": False,
            "expiry_date": date_key,
            "reason": "no overlapping strikes at this expiry",
            "common_expiries": common.get("expiries") or [],
            "disclaimer": _DISCLAIMER,
        }

    spot = float(b_spot or d_spot or 0)
    atm_k = min(shared, key=lambda k: abs(k - spot)) if spot > 0 else shared[len(shared) // 2]
    idx = shared.index(atm_k)
    lo = max(0, idx - n)
    hi = min(len(shared), idx + n + 1)
    chosen = shared[lo:hi]
    warnings: list[str] = []
    if len(chosen) < 2 * n + 1:
        warnings.append(f"only {len(chosen)} shared strikes (requested ATM±{n})")

    now = datetime.now(UTC)
    dte = (b_exp - now).total_seconds() / 86400.0
    ladder: list[dict[str, Any]] = []
    spreads: list[float] = []
    for k in chosen:
        b_iv = float(b_map[k]["iv"])
        d_iv = float(d_map[k]["iv"])
        spread_pp = round((b_iv - d_iv) * 100.0, 2)
        spreads.append(spread_pp)
        ladder.append(
            {
                "strike": k,
                "moneyness_pct": round((k / spot - 1.0) * 100.0, 2) if spot > 0 else None,
                "binance_iv": b_iv,
                "deribit_iv": d_iv,
                "iv_spread_pp": spread_pp,
                "binance_symbol": b_map[k].get("symbol"),
                "deribit_symbol": d_map[k].get("symbol"),
            }
        )

    atm_row = next((r for r in ladder if r["strike"] == atm_k), ladder[len(ladder) // 2])
    atm_spread = float(atm_row["iv_spread_pp"])
    abs_spread = abs(atm_spread)
    if abs_spread < 1.0:
        richer: RicherVenue = "neutral"
        summary = f"{base_u} 同到期 {date_key} ATM IV 接近（差 {atm_spread:+.1f}pp）。"
    elif atm_spread > 0:
        richer = "binance"
        summary = (
            f"{base_u} 同到期 {date_key}：Binance ATM IV 高于 Deribit {atm_spread:.1f}pp。"
        )
    else:
        richer = "deribit"
        summary = (
            f"{base_u} 同到期 {date_key}：Deribit ATM IV 高于 Binance {-atm_spread:.1f}pp。"
        )

    alert = "normal"
    if abs_spread >= _SPREAD_HOT_PP:
        alert = "hot"
    elif abs_spread >= _SPREAD_ELEVATED_PP:
        alert = "elevated"

    max_skew = max(spreads) - min(spreads) if spreads else 0.0
    return {
        "base": base_u,
        "available": True,
        "expiry_date": date_key,
        "binance_expiry": b_exp.isoformat(),
        "deribit_expiry": d_exp.isoformat(),
        "dte": round(dte, 2),
        "binance_spot": b_spot,
        "deribit_spot": d_spot,
        "atm_strike": atm_k,
        "atm": {
            "strike": atm_k,
            "binance_iv": atm_row["binance_iv"],
            "deribit_iv": atm_row["deribit_iv"],
            "iv_spread_pp": atm_spread,
            "binance_symbol": atm_row.get("binance_symbol"),
            "deribit_symbol": atm_row.get("deribit_symbol"),
        },
        "comparison": {
            "iv_spread_pp": atm_spread,
            "abs_spread_pp": round(abs_spread, 2),
            "richer_venue": richer,
            "alert_level": alert,
            "aligned_expiry": True,
            "summary": summary,
            "strike_spread_range_pp": round(max_skew, 2),
        },
        "rows": ladder,
        "common_expiries": common.get("expiries") or [],
        "warnings": warnings,
        "disclaimer": _DISCLAIMER,
    }


def _venue_block(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"enabled": False, "error": "no data"}
    if row.get("error"):
        return {"enabled": False, "error": row["error"], "underlying_price": row.get("underlying_price")}
    if row.get("atm_iv") is None:
        return {"enabled": False, "error": row.get("error", "no iv")}
    return {
        "enabled": True,
        "venue": row.get("venue", "binance"),
        "atm_iv": row.get("atm_iv"),
        "contract": row.get("contract"),
        "expiry": row.get("expiry"),
        "dte": row.get("dte"),
        "strike": row.get("strike"),
        "underlying_price": row.get("underlying_price"),
        "open_interest": row.get("open_interest"),
    }


def compare_atm_row(
    binance_row: dict[str, Any] | None,
    deribit_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare two ATM snapshots for one base."""
    b = _venue_block(binance_row)
    d = _venue_block(deribit_row)
    base = (binance_row or deribit_row or {}).get("base", "?")

    notes: list[str] = []
    if not b["enabled"] or not d["enabled"]:
        return {
            "base": base,
            "binance": b,
            "deribit": d,
            "comparison": {
                "available": False,
                "richer_venue": "unavailable",
                "summary": f"{base} 跨所对比数据不完整（Binance/Deribit 其一不可用）。",
                "notes": notes,
            },
        }

    b_iv = float(b["atm_iv"])
    d_iv = float(d["atm_iv"])
    spread_pp = round((b_iv - d_iv) * 100.0, 2)
    abs_spread = abs(spread_pp)

    if abs_spread < 1.0:
        richer: RicherVenue = "neutral"
        summary = f"{base} 两所近月 ATM IV 接近（差 {spread_pp:+.1f}pp）。"
    elif spread_pp > 0:
        richer = "binance"
        summary = f"{base} Binance ATM IV 高于 Deribit {spread_pp:.1f}pp（买 vol 在 Deribit 相对便宜）。"
    else:
        richer = "deribit"
        summary = f"{base} Deribit ATM IV 高于 Binance {-spread_pp:.1f}pp（买 vol 在 Binance 相对便宜）。"

    b_idx = b.get("underlying_price")
    d_idx = d.get("underlying_price")
    index_spread_pct = None
    if b_idx and d_idx:
        index_spread_pct = round((float(b_idx) - float(d_idx)) / float(d_idx) * 100.0, 3)
        if abs(index_spread_pct) > 0.15:
            notes.append(f"指数价差约 {index_spread_pct:+.2f}%（影响 ATM 对齐）。")

    b_exp = _parse_expiry(str(b.get("expiry") or ""))
    d_exp = _parse_expiry(str(d.get("expiry") or ""))
    dte_gap = None
    aligned_expiry = False
    if b_exp and d_exp:
        dte_gap = round(abs((b_exp - d_exp).total_seconds()) / 86400.0, 1)
        aligned_expiry = dte_gap <= 2.0
        if not aligned_expiry:
            notes.append(f"到期日相差约 {dte_gap:.0f} 天，IV 对比为近似。")

    alert = "normal"
    if abs_spread >= _SPREAD_HOT_PP:
        alert = "hot"
        notes.append("跨所 IV 价差显著，可能存在套利/对冲观察窗口（需计流动性与合约差异）。")
    elif abs_spread >= _SPREAD_ELEVATED_PP:
        alert = "elevated"

    if b.get("dte") is not None and d.get("dte") is not None:
        notes.append(f"DTE：Binance {b['dte']}d · Deribit {d['dte']}d。")

    return {
        "base": base,
        "binance": b,
        "deribit": d,
        "comparison": {
            "available": True,
            "iv_spread_pp": spread_pp,
            "abs_spread_pp": round(abs_spread, 2),
            "richer_venue": richer,
            "alert_level": alert,
            "index_spread_pct": index_spread_pct,
            "dte_gap": dte_gap,
            "aligned_expiry": aligned_expiry,
            "summary": summary,
            "notes": notes,
        },
    }


def _deribit_term_points(base: str, *, client: Any = None) -> list[dict[str, Any]]:
    """Deribit ATM IV term structure points (mirror Binance surface)."""
    idx = deribit_index(base, client=client)
    if idx is None:
        return []
    try:
        summary = fetch_book_summary(base, client=client)
    except Exception:
        return []
    now = datetime.now(UTC)
    by_expiry: dict[datetime, list[dict[str, Any]]] = {}
    for c in _rows_to_candidates(summary, base, idx, min_days=7):
        by_expiry.setdefault(c["expiry"], []).append(c)

    points: list[dict[str, Any]] = []
    for expiry in sorted(by_expiry.keys()):
        pool = by_expiry[expiry]
        calls = [p for p in pool if p.get("side") == "C"]
        use = calls if calls else pool
        best = min(use, key=lambda p: abs(float(p["strike"]) - idx))
        dte = (expiry - now).total_seconds() / 86400.0
        points.append(
            {
                "expiry": expiry.isoformat(),
                "dte": round(dte, 2),
                "atm_strike": best["strike"],
                "atm_iv": round(best["iv"], 6),
                "contract": best.get("symbol"),
                "venue": "deribit",
            }
        )
    return points


def build_term_structure_compare(
    base: str,
    *,
    client: Any = None,
) -> dict[str, Any]:
    """Side-by-side term structure for Binance vs Deribit."""
    base_u = base.upper()
    try:
        b_ts = binance_term_structure(base_u)
    except Exception as e:
        b_ts = {"points": [], "error": str(e)}
    d_points = _deribit_term_points(base_u, client=client)
    return {
        "base": base_u,
        "binance": {
            "spot": b_ts.get("spot"),
            "points": b_ts.get("points") or [],
            "slope_note": b_ts.get("slope_note"),
        },
        "deribit": {
            "spot": deribit_index(base_u, client=client),
            "points": d_points,
        },
        "disclaimer": _DISCLAIMER,
    }


def build_venue_compare(
    base: str,
    *,
    binance_row: dict[str, Any] | None = None,
    deribit_row: dict[str, Any] | None = None,
    expiry_date: str | None = None,
    ladder_n: int = 5,
    client: Any = None,
) -> dict[str, Any]:
    """Single-base Binance vs Deribit compare (near-month + same-expiry aligned)."""
    b_row = binance_row
    d_row = deribit_row
    if b_row is None:
        snaps = binance_atm_snapshot([base.upper()], persist=False, client=client)
        b_row = snaps[0] if snaps else None
        if b_row is not None:
            b_row["venue"] = "binance"
    if d_row is None:
        snaps = deribit_atm_snapshot([base.upper()], client=client)
        d_row = snaps[0] if snaps else None
    out = compare_atm_row(b_row, d_row)
    aligned = build_aligned_expiry_compare(
        base.upper(),
        expiry_date=expiry_date,
        n=ladder_n,
        client=client,
    )
    out["aligned"] = aligned
    out["near_month"] = dict(out.get("comparison") or {})
    if aligned.get("available") and aligned.get("comparison"):
        ac = aligned["comparison"]
        out["comparison"] = {
            **out["comparison"],
            "mode": "aligned_expiry",
            "iv_spread_pp": ac.get("iv_spread_pp"),
            "abs_spread_pp": ac.get("abs_spread_pp"),
            "richer_venue": ac.get("richer_venue"),
            "alert_level": ac.get("alert_level"),
            "aligned_expiry": True,
            "expiry_date": aligned.get("expiry_date"),
            "summary": ac.get("summary"),
            "near_month_iv_spread_pp": out["near_month"].get("iv_spread_pp"),
            "near_month_summary": out["near_month"].get("summary"),
        }
    else:
        out["comparison"]["mode"] = "near_month"
    out["disclaimer"] = _DISCLAIMER
    out["scanned_at"] = now_iso()
    return out


def build_venue_compare_scan(
    symbols: list[str] | None = None,
    *,
    cache_seconds: int = 60,
    client: Any = None,
    data_dir: str = "data/crypto",
    persist_spread: bool = True,
) -> dict[str, Any]:
    """Multi-symbol cross-venue IV scan."""
    syms = [s.upper() for s in (symbols or list(DEFAULT_SYMBOLS))]
    key = ",".join(sorted(syms))
    if cache_seconds > 0 and key in _COMPARE_CACHE:
        ts, payload = _COMPARE_CACHE[key]
        if time.time() - ts < cache_seconds:
            return payload

    b_snaps = {r["base"]: r for r in binance_atm_snapshot(syms, persist=False, client=client)}
    d_snaps = {r["base"]: r for r in deribit_atm_snapshot(syms, client=client)}
    from quant_rd_tool.crypto_options_spread_history import persist_aligned_spread

    items = [
        build_venue_compare(
            s,
            binance_row=b_snaps.get(s),
            deribit_row=d_snaps.get(s),
            client=client,
        )
        for s in syms
    ]
    if persist_spread:
        for item in items:
            aligned = item.get("aligned")
            if isinstance(aligned, dict) and aligned.get("available"):
                try:
                    persist_aligned_spread(aligned, data_dir=data_dir)
                except OSError:
                    pass
    available = [i for i in items if i.get("comparison", {}).get("available")]
    spreads = sorted(
        available,
        key=lambda x: float(x["comparison"].get("abs_spread_pp") or 0),
        reverse=True,
    )
    overview = "暂无有效跨所 IV 对比。"
    if spreads:
        top = spreads[0]
        mode = top["comparison"].get("mode", "near_month")
        label = "同到期" if mode == "aligned_expiry" else "近月"
        overview = (
            f"最大{label}价差：{top['base']} "
            f"{top['comparison']['iv_spread_pp']:+.1f}pp "
            f"（{top['comparison']['richer_venue']} 偏高）。"
        )

    from quant_rd_tool.crypto_options_spread_alerts import process_spread_alerts

    spread_alerts = process_spread_alerts(
        {"items": items},
        data_dir=data_dir,
    )
    payload = {
        "scanned_at": now_iso(),
        "symbols": syms,
        "items": items,
        "overview": overview,
        "spread_alerts": spread_alerts,
        "disclaimer": _DISCLAIMER,
    }
    if cache_seconds > 0:
        _COMPARE_CACHE[key] = (time.time(), payload)
    return payload
