"""Score options IV: percentile, 24h change, cross-symbol rank."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

_VOL_SCAN_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

from quant_rd_tool.crypto_options_data import (
    DEFAULT_SYMBOLS,
    fetch_atm_iv_snapshot,
    load_history,
)

AlertLevel = Literal["normal", "elevated", "hot"]

_DEFAULT_CONFIG = {
    "symbols": list(DEFAULT_SYMBOLS),
    "lookback_days": 30,
    "iv_percentile_threshold": 80.0,
    "iv_change_24h_threshold": 10.0,
    "data_dir": "data/crypto",
}


def _settings_path(data_dir: str | Path) -> Path:
    return Path(data_dir).parent / "settings.json"


def get_scan_config(data_dir: str = "data/crypto") -> dict[str, Any]:
    path = _settings_path(data_dir)
    cfg = dict(_DEFAULT_CONFIG)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            ent = raw.get("crypto_options_vol") or {}
            if isinstance(ent, dict):
                cfg.update({k: ent[k] for k in cfg if k in ent})
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_scan_config(**updates: Any) -> dict[str, Any]:
    data_dir = str(updates.get("data_dir") or _DEFAULT_CONFIG["data_dir"])
    path = _settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
    ent = raw.get("crypto_options_vol")
    if not isinstance(ent, dict):
        ent = {}
    cfg = get_scan_config(data_dir)
    for k in (
        "symbols",
        "lookback_days",
        "iv_percentile_threshold",
        "iv_change_24h_threshold",
    ):
        if k in updates and updates[k] is not None:
            ent[k] = updates[k]
            cfg[k] = updates[k]
    raw["crypto_options_vol"] = ent
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def _parse_ts(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def iv_percentile(current_iv: float, history_ivs: list[float]) -> float | None:
    if not history_ivs:
        return None
    sorted_ivs = sorted(history_ivs)
    rank = sum(1 for v in sorted_ivs if v <= current_iv)
    return round(100.0 * rank / len(sorted_ivs), 2)


def iv_change_24h(current_iv: float, history: list[dict[str, Any]]) -> float | None:
    if not history:
        return None
    now = datetime.now(UTC)
    target = now - timedelta(hours=24)
    best: dict[str, Any] | None = None
    best_delta = timedelta(days=999)
    for row in history:
        iv = row.get("atm_iv")
        ts = row.get("ts")
        if iv is None or not ts:
            continue
        dt = _parse_ts(str(ts))
        if not dt:
            continue
        delta = abs(dt - target)
        if delta < best_delta:
            best_delta = delta
            best = row
    if not best or best.get("atm_iv") in (None, 0):
        return None
    prev = float(best["atm_iv"])
    if prev <= 0:
        return None
    return round((current_iv - prev) / prev * 100.0, 2)


def _history_ivs(base: str, *, data_dir: str, lookback_days: int) -> list[float]:
    hist = load_history(base, data_dir=data_dir, limit=2000)
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    ivs: list[float] = []
    for row in hist:
        ts = _parse_ts(str(row.get("ts") or ""))
        iv = row.get("atm_iv")
        if ts and ts >= cutoff and iv is not None:
            try:
                ivs.append(float(iv))
            except (TypeError, ValueError):
                continue
    return ivs


def _alert_level(
    *,
    pct: float | None,
    chg: float | None,
    pct_thr: float,
    chg_thr: float,
) -> AlertLevel:
    hot = 0
    elevated = 0
    if pct is not None and pct >= pct_thr:
        elevated += 1
        if pct >= min(95, pct_thr + 10):
            hot += 1
    if chg is not None and chg >= chg_thr:
        elevated += 1
        if chg >= chg_thr * 2:
            hot += 1
    if hot >= 1 or elevated >= 2:
        return "hot"
    if elevated >= 1:
        return "elevated"
    return "normal"


def _cache_key(data_dir: str, symbols: list[str]) -> str:
    return f"{data_dir}|{','.join(sorted(s.upper() for s in symbols))}"


def clear_vol_scan_cache(data_dir: str | None = None) -> None:
    if not data_dir:
        _VOL_SCAN_CACHE.clear()
        return
    prefix = f"{data_dir}|"
    for key in list(_VOL_SCAN_CACHE):
        if key.startswith(prefix):
            del _VOL_SCAN_CACHE[key]


def get_or_run_volatility_scan(
    *,
    symbols: list[str] | None = None,
    lookback_days: int | None = None,
    data_dir: str | None = None,
    persist_snapshot: bool = True,
    client: Any = None,
    cache_seconds: int = 60,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Cached wrapper for analyze/scheduler bursts (one EAPI round-trip per TTL)."""
    cfg = get_scan_config(data_dir or _DEFAULT_CONFIG["data_dir"])
    syms = [s.upper() for s in (symbols or cfg["symbols"])]
    dd = str(data_dir or cfg["data_dir"])
    key = _cache_key(dd, syms)
    if use_cache and cache_seconds > 0 and key in _VOL_SCAN_CACHE:
        ts, payload = _VOL_SCAN_CACHE[key]
        if time.time() - ts < cache_seconds:
            return payload
    scan = run_volatility_scan(
        symbols=syms,
        lookback_days=lookback_days,
        data_dir=dd,
        persist_snapshot=persist_snapshot,
        client=client,
    )
    if cache_seconds > 0:
        _VOL_SCAN_CACHE[key] = (time.time(), scan)
    return scan


def run_volatility_scan(
    *,
    symbols: list[str] | None = None,
    lookback_days: int | None = None,
    data_dir: str | None = None,
    persist_snapshot: bool = True,
    client: Any = None,
) -> dict[str, Any]:
    cfg = get_scan_config(data_dir or _DEFAULT_CONFIG["data_dir"])
    syms = [s.upper() for s in (symbols or cfg["symbols"])]
    lb = int(lookback_days if lookback_days is not None else cfg["lookback_days"])
    dd = str(data_dir or cfg["data_dir"])
    pct_thr = float(cfg["iv_percentile_threshold"])
    chg_thr = float(cfg["iv_change_24h_threshold"])

    snapshots = fetch_atm_iv_snapshot(
        syms,
        data_dir=dd,
        persist=persist_snapshot,
        client=client,
    )

    items: list[dict[str, Any]] = []
    for snap in snapshots:
        base = snap["base"]
        iv = snap.get("atm_iv")
        if iv is None:
            items.append(
                {
                    "base": base,
                    "error": snap.get("error", "missing iv"),
                    "alert_level": "normal",
                    "composite_score": 0.0,
                }
            )
            continue
        iv_f = float(iv)
        hist_ivs = _history_ivs(base, data_dir=dd, lookback_days=lb)
        hist_rows = load_history(base, data_dir=dd, limit=500)
        pct = iv_percentile(iv_f, hist_ivs)
        chg = iv_change_24h(iv_f, hist_rows[:-1] if hist_rows else [])
        level = _alert_level(pct=pct, chg=chg, pct_thr=pct_thr, chg_thr=chg_thr)
        alerts: list[str] = []
        if pct is not None and pct >= pct_thr:
            alerts.append("iv_percentile_high")
        if chg is not None and chg >= chg_thr:
            alerts.append("iv_change_24h_high")
        cold_start = len(hist_ivs) < 5
        items.append(
            {
                "base": base,
                "ts": snap.get("ts"),
                "atm_iv": iv_f,
                "underlying_price": snap.get("underlying_price"),
                "contract": snap.get("contract"),
                "expiry": snap.get("expiry"),
                "dte": snap.get("dte"),
                "iv_percentile": pct,
                "iv_change_24h_pct": chg,
                "alert_level": level,
                "alerts": alerts,
                "cold_start": cold_start,
                "composite_score": 0.0,
            }
        )

    # composite: percentile + normalized change + rank
    valid = [i for i in items if i.get("atm_iv") is not None]
    max_chg = max((abs(i["iv_change_24h_pct"] or 0) for i in valid), default=1.0) or 1.0
    for i in valid:
        pct_part = (i.get("iv_percentile") or 50) / 100.0
        chg_val = i.get("iv_change_24h_pct")
        chg_part = (max(0.0, float(chg_val)) / max_chg) if chg_val is not None else 0.0
        i["composite_score"] = round(0.5 * pct_part + 0.5 * chg_part, 4)

    valid.sort(key=lambda x: x["composite_score"], reverse=True)
    for rank, row in enumerate(valid, start=1):
        row["rank"] = rank

    payload = {
        "scanned_at": datetime.now(UTC).isoformat(),
        "config": {**cfg, "symbols": syms, "lookback_days": lb, "data_dir": dd},
        "items": items,
    }
    if persist_snapshot:
        clear_vol_scan_cache(dd)
        key = _cache_key(dd, syms)
        _VOL_SCAN_CACHE[key] = (time.time(), payload)
    return payload


def run_options_iv_maintenance(
    *,
    data_dir: str | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """
    Persist ATM IV snapshots for all configured symbols (scheduler / cron).

    Returns scan summary; does not require spot OHLCV.
    """
    from quant_rd_tool.crypto_options_advisor import build_scan_advice

    scan = run_volatility_scan(
        symbols=None,
        data_dir=data_dir,
        persist_snapshot=True,
        client=client,
    )
    clear_vol_scan_cache(str(data_dir or _DEFAULT_CONFIG["data_dir"]))
    advice = build_scan_advice(scan)
    hot = [i for i in scan.get("items") or [] if i.get("alert_level") in ("hot", "elevated")]
    venue_compare_pack = None
    try:
        from quant_rd_tool.crypto_options_compare import build_venue_compare_scan

        venue_compare_pack = build_venue_compare_scan(
            [i.get("base") for i in scan.get("items") or [] if i.get("base")],
            data_dir=str(data_dir or _DEFAULT_CONFIG["data_dir"]),
            persist_spread=True,
        )
    except Exception:
        pass
    return {
        **scan,
        "advice_pack": advice,
        "elevated_count": len(hot),
        "elevated_bases": [i.get("base") for i in hot],
        "venue_compare_pack": venue_compare_pack,
    }
