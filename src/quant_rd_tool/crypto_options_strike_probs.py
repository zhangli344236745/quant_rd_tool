"""ATM ±N strike ladder — qlib/GBM model vs Binance IV risk-neutral probabilities."""

from __future__ import annotations

import copy
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analysis import crypto_root, format_period_bounds
from quant_rd_tool.crypto_options_data import (
    fetch_index_price,
    fetch_mark_rows,
    parse_option_symbol,
    pick_atm_contract,
)
from quant_rd_tool.crypto_storage import load_ohlcv_csv, ohlcv_csv_path, qlib_dir_for
from quant_rd_tool.qlib_dump import QlibDataDumper

_DEFAULT_CONFIG = {
    "default_n": 5,
    "min_dte": 7,
    "vol_lookback_days": 30,
    "cache_seconds": 60,
    "timeframe": "1d",
    "mu_cap_ann": 2.0,
    "include_strike_ladder_in_analyze": True,
    "analyze_ladder_n": 3,
}

_DISCLAIMER = (
    "研究用途。模型概率（历史波动 + qlib 漂移，GBM）与期权隐含概率（风险中性）口径不同，不构成投资建议。"
)

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _settings_path(data_dir: str | Path) -> Path:
    return Path(data_dir).parent / "settings.json"


def get_strike_prob_config(data_dir: str = "data/crypto") -> dict[str, Any]:
    cfg = dict(_DEFAULT_CONFIG)
    path = _settings_path(data_dir)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            ent = raw.get("crypto_options_strike_probs") or {}
            if isinstance(ent, dict):
                cfg.update({k: ent[k] for k in cfg if k in ent})
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def annualized_realized_vol(closes: pd.Series, lookback_days: int) -> float | None:
    s = closes.astype(float).dropna()
    if len(s) < max(lookback_days, 5):
        return None
    tail = s.tail(lookback_days + 1)
    log_r = (tail / tail.shift(1)).apply(lambda x: math.log(x) if x and x > 0 else float("nan"))
    log_r = log_r.dropna()
    if len(log_r) < 5:
        return None
    daily = float(log_r.std())
    if daily <= 0 or math.isnan(daily):
        return None
    return daily * math.sqrt(252)


def scale_predicted_return_to_annual(predicted_return: float | None, *, bars_per_year: float = 252.0) -> float:
    if predicted_return is None:
        return 0.0
    mu = float(predicted_return) * bars_per_year
    return max(-_DEFAULT_CONFIG["mu_cap_ann"], min(_DEFAULT_CONFIG["mu_cap_ann"], mu))


def prob_expiry_itm_call(
    spot: float,
    strike: float,
    *,
    mu_ann: float,
    sigma_ann: float,
    dte_days: float,
) -> float | None:
    """P(S_T >= K) under GBM with drift mu_ann and vol sigma_ann (physical approx)."""
    if spot <= 0 or strike <= 0 or sigma_ann <= 0 or dte_days <= 0:
        return None
    t = dte_days / 365.0
    a = mu_ann - 0.5 * sigma_ann**2
    denom = sigma_ann * math.sqrt(t)
    if denom <= 0:
        return None
    z = (math.log(strike / spot) - a * t) / denom
    return max(0.0, min(1.0, 1.0 - norm_cdf(z)))


def prob_touch_call_up(
    spot: float,
    strike: float,
    *,
    mu_ann: float,
    sigma_ann: float,
    dte_days: float,
) -> float | None:
    """P(max_{0<=t<=T} S_t >= K) — upward touch, call-oriented."""
    if spot <= 0 or strike <= 0 or sigma_ann <= 0 or dte_days <= 0:
        return None
    if strike <= spot:
        return 1.0
    t = dte_days / 365.0
    a = mu_ann - 0.5 * sigma_ann**2
    sig_sqrt_t = sigma_ann * math.sqrt(t)
    if sig_sqrt_t <= 0:
        return None
    ln_ratio = math.log(spot / strike)
    x = (ln_ratio + a * t) / sig_sqrt_t
    y = (ln_ratio - a * t) / sig_sqrt_t
    expo = 2.0 * a * math.log(strike / spot) / (sigma_ann**2)
    p = norm_cdf(x) + math.exp(expo) * norm_cdf(y)
    return max(0.0, min(1.0, p))


def prob_implied_expiry_itm_call(
    spot: float,
    strike: float,
    *,
    iv: float,
    dte_days: float,
    risk_free: float = 0.0,
) -> float | None:
    """Risk-neutral P(S_T >= K) from Black–Scholes N(d2), r≈0."""
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_days <= 0:
        return None
    t = dte_days / 365.0
    sig_sqrt_t = iv * math.sqrt(t)
    if sig_sqrt_t <= 0:
        return None
    d2 = (math.log(spot / strike) + (risk_free - 0.5 * iv**2) * t) / sig_sqrt_t
    return max(0.0, min(1.0, norm_cdf(d2)))


def _parse_marks_for_expiry(
    marks: list[dict[str, Any]],
    base: str,
    expiry: datetime,
) -> dict[float, dict[str, Any]]:
    """Map strike -> best row (prefer call) for one expiry."""
    exp_key = expiry.date()
    by_strike: dict[float, dict[str, Any]] = {}
    for row in marks:
        sym = str(row.get("symbol") or "")
        meta = parse_option_symbol(sym)
        if not meta or meta["base"] != base.upper():
            continue
        if meta["expiry"].date() != exp_key:
            continue
        iv_raw = row.get("markIV") or row.get("askIV") or row.get("bidIV")
        try:
            iv = float(iv_raw)
        except (TypeError, ValueError):
            continue
        if iv <= 0 or iv > 5:
            continue
        k = float(meta["strike"])
        side = meta["side"]
        prev = by_strike.get(k)
        if prev is None or (side == "C" and prev.get("side") != "C"):
            by_strike[k] = {
                "strike": k,
                "symbol": sym,
                "side": side,
                "mark_iv": iv,
                "mark_price": row.get("markPrice"),
            }
    return by_strike


def build_strike_ladder(
    marks: list[dict[str, Any]],
    base: str,
    spot: float,
    n: int,
    *,
    expiry: datetime | None = None,
    min_dte: int = 7,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Return ATM±n strikes for one expiry (calls preferred for IV).

    If expiry is None, uses the same near-month pick as ATM IV scan.
    """
    warnings: list[str] = []
    base_u = base.upper()
    if expiry is None:
        atm = pick_atm_contract(marks, base_u, spot, min_days=min_dte)
        if not atm:
            return [], ["no ATM contract to infer expiry"]
        expiry = datetime.fromisoformat(atm["expiry"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)

    by_strike = _parse_marks_for_expiry(marks, base_u, expiry)
    if not by_strike:
        return [], [f"no option marks for expiry {expiry.date().isoformat()}"]

    strikes = sorted(by_strike.keys())
    atm_k = min(strikes, key=lambda k: abs(k - spot))
    idx = strikes.index(atm_k)
    lo = max(0, idx - n)
    hi = min(len(strikes), idx + n + 1)
    chosen = strikes[lo:hi]
    if len(chosen) < 2 * n + 1:
        warnings.append(f"only {len(chosen)} strikes available (requested ATM±{n})")

    now = datetime.now(UTC)
    dte = (expiry - now).total_seconds() / 86400.0
    rows: list[dict[str, Any]] = []
    for k in chosen:
        ent = dict(by_strike[k])
        ent["moneyness_pct"] = round((k / spot - 1.0) * 100.0, 2)
        ent["dte"] = round(dte, 2)
        ent["expiry"] = expiry.isoformat()
        rows.append(ent)
    return rows, warnings


def _load_spot_frame(data_dir: str, base: str, timeframe: str) -> pd.DataFrame | None:
    root = crypto_root(data_dir, base)
    path = ohlcv_csv_path(root, timeframe)
    return load_ohlcv_csv(path)


def _try_qlib_drift(
    df: pd.DataFrame,
    base: str,
    *,
    data_dir: str,
    timeframe: str,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_ml import run_crypto_ml_analysis

    root = crypto_root(data_dir, base)
    qlib_dir = qlib_dir_for(root, timeframe)
    qlib_code = cxt.to_qlib_code(base)
    qlib_freq = cxt.timeframe_to_qlib_freq(timeframe)
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    QlibDataDumper(qlib_dir, freq=qlib_freq).dump({qlib_code: work})
    start_date, end_date = format_period_bounds(work, timeframe)
    ml = run_crypto_ml_analysis(
        str(qlib_dir.resolve()),
        qlib_code,
        start_date=start_date,
        end_date=end_date,
        num_bars=len(work),
        algorithm="lgb",
        timeframe=timeframe,
    )
    if not ml.get("enabled"):
        return {"enabled": False, "reason": ml.get("reason") or "qlib ml skipped"}
    block = ml
    if ml.get("algorithm") == "both" and ml.get("models"):
        pref = (ml.get("comparison") or {}).get("preferred_by_ic")
        models = ml.get("models") or {}
        if pref and pref in models:
            block = models[pref]
        else:
            block = next((m for m in models.values() if m.get("enabled")), ml)
    latest = block.get("latest") or {}
    pred = latest.get("predicted_return")
    return {
        "enabled": True,
        "signal": latest.get("signal"),
        "predicted_return": pred,
        "mu_ann": scale_predicted_return_to_annual(pred),
    }


def build_strike_probability_report(
    base: str,
    *,
    n: int | None = None,
    data_dir: str = "data/crypto",
    expiry_iso: str | None = None,
    client: Any = None,
    spot_stance: str | None = None,
    iv_alert_level: str | None = None,
    iv_percentile: float | None = None,
    with_purchase_advice: bool = True,
) -> dict[str, Any]:
    cfg = get_strike_prob_config(data_dir)
    n_eff = int(n if n is not None else cfg["default_n"])
    cache_key = f"{base.upper()}:{n_eff}:{expiry_iso or ''}:{data_dir}"
    ttl = int(cfg.get("cache_seconds") or 0)
    if ttl > 0 and cache_key in _CACHE:
        ts, payload = _CACHE[cache_key]
        if time.time() - ts < ttl:
            out = copy.deepcopy(payload)
            if with_purchase_advice and out.get("rows"):
                from quant_rd_tool.crypto_options_strike_advisor import (
                    enrich_strike_report_with_advice,
                )

                enrich_strike_report_with_advice(
                    out,
                    spot_stance=spot_stance or "中性",
                    iv_alert_level=iv_alert_level or "normal",
                    iv_percentile=iv_percentile,
                )
            return out

    marks = fetch_mark_rows(client=client)
    spot = fetch_index_price(base, client=client)
    if spot is None:
        raise ValueError(f"index price unavailable for {base}")

    expiry_dt: datetime | None = None
    if expiry_iso:
        expiry_dt = datetime.fromisoformat(expiry_iso.replace("Z", "+00:00"))
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=UTC)

    ladder, warnings = build_strike_ladder(
        marks,
        base,
        spot,
        n_eff,
        expiry=expiry_dt,
        min_dte=int(cfg.get("min_dte") or 7),
    )
    if not ladder:
        return {
            "base": base.upper(),
            "spot": spot,
            "n": n_eff,
            "rows": [],
            "warnings": warnings,
            "disclaimer": _DISCLAIMER,
            "model": {"enabled": False, "reason": "no strike ladder"},
        }

    dte = float(ladder[0].get("dte") or 0)
    expiry_out = ladder[0].get("expiry")

    timeframe = str(cfg.get("timeframe") or "1d")
    df = _load_spot_frame(data_dir, base, timeframe)
    sigma_ann: float | None = None
    qlib_block: dict[str, Any] = {"enabled": False, "reason": "no OHLCV"}
    mu_ann = 0.0

    if df is not None and not df.empty and "close" in df.columns:
        lookback = int(cfg.get("vol_lookback_days") or 30)
        sigma_ann = annualized_realized_vol(df["close"], lookback)
        try:
            qlib_block = _try_qlib_drift(df, base, data_dir=data_dir, timeframe=timeframe)
        except Exception as e:
            qlib_block = {"enabled": False, "reason": str(e)}
        if qlib_block.get("enabled"):
            mu_ann = float(qlib_block.get("mu_ann") or 0.0)

    model_enabled = sigma_ann is not None and sigma_ann > 0
    model_meta: dict[str, Any] = {
        "enabled": model_enabled,
        "sigma_ann": round(sigma_ann, 6) if sigma_ann else None,
        "mu_ann": round(mu_ann, 6),
        "qlib": qlib_block,
        "assumptions": "GBM; realized vol + qlib drift; physical approx for model leg",
    }
    if not model_enabled:
        model_meta["reason"] = qlib_block.get("reason") or "insufficient OHLCV for realized vol"

    out_rows: list[dict[str, Any]] = []
    for leg in ladder:
        strike = float(leg["strike"])
        iv = float(leg["mark_iv"])
        model_exp = (
            prob_expiry_itm_call(spot, strike, mu_ann=mu_ann, sigma_ann=sigma_ann, dte_days=dte)
            if model_enabled and sigma_ann
            else None
        )
        model_touch = (
            prob_touch_call_up(spot, strike, mu_ann=mu_ann, sigma_ann=sigma_ann, dte_days=dte)
            if model_enabled and sigma_ann
            else None
        )
        impl_exp = prob_implied_expiry_itm_call(spot, strike, iv=iv, dte_days=dte)
        edge = None
        if model_exp is not None and impl_exp is not None:
            edge = round(model_exp - impl_exp, 4)
        out_rows.append(
            {
                "strike": strike,
                "side": leg.get("side"),
                "symbol": leg.get("symbol"),
                "moneyness_pct": leg.get("moneyness_pct"),
                "mark_iv": round(iv, 6),
                "model": {
                    "expiry_itm_call": round(model_exp, 4) if model_exp is not None else None,
                    "touch_call": round(model_touch, 4) if model_touch is not None else None,
                },
                "implied": {
                    "expiry_itm_call": round(impl_exp, 4) if impl_exp is not None else None,
                    "touch_call": None,
                },
                "edge_expiry": edge,
            }
        )

    payload: dict[str, Any] = {
        "base": base.upper(),
        "spot": round(spot, 4),
        "expiry": expiry_out,
        "dte": dte,
        "n": n_eff,
        "model": model_meta,
        "rows": out_rows,
        "warnings": warnings,
        "disclaimer": _DISCLAIMER,
    }
    if ttl > 0:
        _CACHE[cache_key] = (time.time(), payload)

    if with_purchase_advice and payload.get("rows"):
        from quant_rd_tool.crypto_options_strike_advisor import enrich_strike_report_with_advice

        enrich_strike_report_with_advice(
            payload,
            spot_stance=spot_stance or "中性",
            iv_alert_level=iv_alert_level or "normal",
            iv_percentile=iv_percentile,
        )
    return payload
