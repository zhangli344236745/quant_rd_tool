"""Historical-simulation VaR and CVaR for crypto symbols and perp portfolios."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.config import settings

MIN_OBSERVATIONS = 30
DEFAULT_MC_SIMS = 10_000
STRESS_SHOCKS = (-0.03, -0.05, -0.10, -0.20)
NORMAL_Z: dict[float, float] = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
TRADING_DAYS_PER_YEAR = 252


def returns_from_close(close: pd.Series) -> pd.Series:
    return close.astype(float).pct_change().dropna()


def _scale_returns(returns: pd.Series, horizon_days: int) -> pd.Series:
    if horizon_days <= 1:
        return returns
    return returns * (horizon_days**0.5)


def compute_historical_var(
    returns: pd.Series,
    *,
    confidence: float,
    horizon_days: int = 1,
) -> float:
    r = _scale_returns(returns.dropna(), horizon_days)
    if len(r) < MIN_OBSERVATIONS:
        raise ValueError(f"insufficient data: need >={MIN_OBSERVATIONS}, got {len(r)}")
    q = float(r.quantile(1 - confidence))
    return round(max(-q, 0.0), 8)


def compute_cvar(
    returns: pd.Series,
    *,
    confidence: float,
    horizon_days: int = 1,
) -> float:
    r = _scale_returns(returns.dropna(), horizon_days)
    if len(r) < MIN_OBSERVATIONS:
        raise ValueError(f"insufficient data: need >={MIN_OBSERVATIONS}, got {len(r)}")
    var_pct = compute_historical_var(returns, confidence=confidence, horizon_days=horizon_days)
    tail = r[r <= -var_pct]
    if tail.empty:
        tail = r[r <= r.quantile(1 - confidence)]
    cvar = -float(tail.mean()) if len(tail) else var_pct
    return round(max(cvar, var_pct), 8)


def parse_confidence_levels(confidence: str) -> list[float]:
    levels: list[float] = []
    for part in str(confidence).split(","):
        part = part.strip()
        if not part:
            continue
        levels.append(float(part))
    if not levels:
        levels = [0.95, 0.99]
    return levels


def confidence_key(c: float) -> str:
    return f"{c:.2f}"


def _normal_z(confidence: float) -> float:
    if confidence in NORMAL_Z:
        return NORMAL_Z[confidence]
    return math.sqrt(2) * _erfinv(2 * confidence - 1)


def _erfinv(x: float) -> float:
    """Approximate inverse error function (Abramowitz & Stegun)."""
    a = 0.147
    sign = 1 if x >= 0 else -1
    x = abs(x)
    ln = math.log(1 - x * x)
    first = 2 / (math.pi * a) + ln / 2
    second = ln / a
    return sign * math.sqrt(math.sqrt(first * first - second) - first)


def _estimate_student_t_df(returns: pd.Series) -> float:
    """Method-of-moments df from excess kurtosis; clamp for stability."""
    r = returns.dropna()
    if len(r) < MIN_OBSERVATIONS:
        return 5.0
    kurt = float(r.kurtosis())
    if not np.isfinite(kurt) or kurt <= 0:
        return 8.0
    df = 6.0 / kurt + 4.0
    return float(min(max(df, 3.5), 30.0))


def _mc_var_cvar_from_sims(sims: np.ndarray, *, confidence: float) -> tuple[float, float]:
    q = float(np.quantile(sims, 1 - confidence))
    var_pct = round(max(-q, 0.0), 8)
    tail = sims[sims <= -var_pct]
    if tail.size == 0:
        tail = sims[sims <= q]
    cvar_pct = round(max(-float(tail.mean()), var_pct), 8) if tail.size else var_pct
    return var_pct, cvar_pct


def compute_monte_carlo_var(
    returns: pd.Series,
    *,
    confidence: float,
    horizon_days: int = 1,
    n_sims: int = DEFAULT_MC_SIMS,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Monte Carlo horizon P&L% simulations: GBM (normal) and Student-t (fat tails).
    Positive var_pct = loss fraction.
    """
    r = returns.dropna()
    if len(r) < MIN_OBSERVATIONS:
        raise ValueError(f"insufficient data: need >={MIN_OBSERVATIONS}, got {len(r)}")
    h = max(1, int(horizon_days))
    mu_d = float(r.mean())
    sigma_d = float(r.std(ddof=1))
    if sigma_d <= 0:
        sigma_d = 1e-8
    mu_h = mu_d * h
    sigma_h = sigma_d * math.sqrt(h)

    rng = np.random.default_rng(seed)
    n = max(1000, int(n_sims))

    # GBM: horizon arithmetic return ~ Normal(mu_h, sigma_h)
    sims_gbm = rng.normal(mu_h, sigma_h, n)
    gbm_var, gbm_cvar = _mc_var_cvar_from_sims(sims_gbm, confidence=confidence)

    # Student-t: match horizon volatility, heavier tails
    df = _estimate_student_t_df(r)
    t_raw = rng.standard_t(df, n)
    if df > 2:
        t_scale = sigma_h * math.sqrt(df / (df - 2.0))
    else:
        t_scale = sigma_h
    sims_t = mu_h + t_raw * t_scale
    t_var, t_cvar = _mc_var_cvar_from_sims(sims_t, confidence=confidence)

    return {
        "n_simulations": n,
        "seed": seed,
        "horizon_days": h,
        "gbm": {
            "var_pct": gbm_var,
            "cvar_pct": gbm_cvar,
            "label": "normal_gbm",
        },
        "student_t": {
            "var_pct": t_var,
            "cvar_pct": t_cvar,
            "df": round(df, 2),
            "label": "student_t",
        },
    }


def compute_parametric_var(
    returns: pd.Series,
    *,
    confidence: float,
    horizon_days: int = 1,
) -> float:
    """Variance-covariance VaR assuming normal returns (positive = loss fraction)."""
    r = _scale_returns(returns.dropna(), horizon_days)
    if len(r) < MIN_OBSERVATIONS:
        raise ValueError(f"insufficient data: need >={MIN_OBSERVATIONS}, got {len(r)}")
    mu = float(r.mean())
    sigma = float(r.std(ddof=1))
    if sigma <= 0:
        return round(max(-mu, 0.0), 8)
    z = _normal_z(confidence)
    var_pct = -(mu - z * sigma)
    return round(max(var_pct, 0.0), 8)


def summarize_returns(returns: pd.Series) -> dict[str, float | None]:
    r = returns.dropna()
    if len(r) < 2:
        return {}
    daily_vol = float(r.std(ddof=1))
    ann_vol = daily_vol * math.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(r.skew()) if len(r) >= 3 else None
    kurt = float(r.kurtosis()) if len(r) >= 4 else None
    return {
        "mean_daily_return": round(float(r.mean()), 8),
        "daily_volatility": round(daily_vol, 8),
        "annualized_volatility": round(ann_vol, 6),
        "skewness": round(skew, 4) if skew is not None and not np.isnan(skew) else None,
        "excess_kurtosis": round(kurt, 4) if kurt is not None and not np.isnan(kurt) else None,
        "worst_day_return": round(float(r.min()), 6),
        "best_day_return": round(float(r.max()), 6),
    }


def backtest_var(
    returns: pd.Series,
    var_pct: float,
    *,
    confidence: float,
) -> dict[str, Any]:
    r = returns.dropna()
    if r.empty:
        return {}
    violations = r < -var_pct
    n = int(len(r))
    count = int(violations.sum())
    expected = 1 - confidence
    actual = count / n if n else 0.0
    worst = float(r.min())
    max_exceed = float((-r[violations] - var_pct).max()) if count else 0.0
    return {
        "observations": n,
        "violations": count,
        "expected_violation_rate": round(expected, 6),
        "actual_violation_rate": round(actual, 6),
        "violation_ratio": round(actual / expected, 4) if expected > 0 else None,
        "worst_day_return": round(worst, 6),
        "max_exceedance_pct": round(max_exceed, 6),
        "backtest_ok": actual <= expected * 2.5 if expected > 0 else True,
    }


def stress_scenarios(notional_usdt: float, shocks: tuple[float, ...] = STRESS_SHOCKS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for shock in shocks:
        loss_pct = abs(shock)
        rows.append(
            {
                "shock_pct": round(shock * 100, 2),
                "loss_pct": round(loss_pct, 6),
                "loss_usdt": round(notional_usdt * loss_pct, 4),
            }
        )
    return rows


def return_histogram(returns: pd.Series, *, bins: int = 20) -> list[dict[str, Any]]:
    r = returns.dropna()
    if len(r) < MIN_OBSERVATIONS:
        return []
    counts, edges = np.histogram(r, bins=bins)
    out: list[dict[str, Any]] = []
    for i, c in enumerate(counts):
        out.append(
            {
                "bin_low": round(float(edges[i]), 6),
                "bin_high": round(float(edges[i + 1]), 6),
                "count": int(c),
            }
        )
    return out


def correlation_matrix(rets_map: dict[str, pd.Series]) -> dict[str, Any]:
    if len(rets_map) < 2:
        return {"symbols": list(rets_map.keys()), "matrix": []}
    df = pd.concat(rets_map.values(), axis=1, join="inner")
    df.columns = list(rets_map.keys())
    corr = df.corr()
    symbols = list(corr.columns)
    matrix = []
    for a in symbols:
        row = [round(float(corr.loc[a, b]), 4) if pd.notna(corr.loc[a, b]) else None for b in symbols]
        matrix.append(row)
    return {"symbols": symbols, "matrix": matrix}


def _metrics_block(
    rets: pd.Series,
    *,
    notional_usdt: float,
    confidence_levels: list[float],
    horizon_days: int,
    mc_n_sims: int = DEFAULT_MC_SIMS,
    mc_seed: int = 42,
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for c in confidence_levels:
        key = confidence_key(c)
        hist_var = compute_historical_var(rets, confidence=c, horizon_days=horizon_days)
        cvar_pct = compute_cvar(rets, confidence=c, horizon_days=horizon_days)
        try:
            param_var = compute_parametric_var(rets, confidence=c, horizon_days=horizon_days)
        except ValueError:
            param_var = None
        try:
            mc = compute_monte_carlo_var(
                rets,
                confidence=c,
                horizon_days=horizon_days,
                n_sims=mc_n_sims,
                seed=mc_seed,
            )
            gbm = mc["gbm"]
            st = mc["student_t"]
            mc_block = {
                **mc,
                "gbm": {
                    **gbm,
                    "var_usdt": round(notional_usdt * gbm["var_pct"], 4),
                    "cvar_usdt": round(notional_usdt * gbm["cvar_pct"], 4),
                },
                "student_t": {
                    **st,
                    "var_usdt": round(notional_usdt * st["var_pct"], 4),
                    "cvar_usdt": round(notional_usdt * st["cvar_pct"], 4),
                },
            }
        except ValueError:
            mc_block = None
        metrics[key] = {
            "var_pct": hist_var,
            "cvar_pct": cvar_pct,
            "var_usdt": round(notional_usdt * hist_var, 4),
            "cvar_usdt": round(notional_usdt * cvar_pct, 4),
            "parametric_var_pct": param_var,
            "parametric_var_usdt": round(notional_usdt * param_var, 4) if param_var is not None else None,
            "method_spread_pct": round(hist_var - param_var, 6) if param_var is not None else None,
            "monte_carlo": mc_block,
            "backtest": backtest_var(rets, hist_var, confidence=c),
        }
    return metrics


def build_symbol_narrative(
    report: dict[str, Any],
    *,
    stats: dict[str, float | None],
) -> dict[str, Any]:
    sym = report.get("symbol", "")
    obs = report.get("observations", 0)
    hi = report.get("metrics", {}).get("0.99") or report.get("metrics", {}).get(
        next(iter(report.get("metrics", {})), "")
    )
    lines: list[str] = []
    if hi:
        lines.append(
            f"{sym} 在 {report.get('params', {}).get('horizon_days', 1)} 日、"
            f"{float(hi.get('var_pct', 0)) * 100:.2f}% 历史 VaR 下，"
            f"名义 {report.get('notional_usdt')} USDT 的预估最大损失约 {hi.get('var_usdt')} USDT。"
        )
        bt = hi.get("backtest") or {}
        if bt:
            lines.append(
                f"回测：样本 {bt.get('observations')} 期中违规 {bt.get('violations')} 次，"
                f"实际违规率 {float(bt.get('actual_violation_rate', 0)) * 100:.2f}% "
                f"(期望约 {float(bt.get('expected_violation_rate', 0)) * 100:.2f}%)。"
            )
        spread = hi.get("method_spread_pct")
        if spread is not None and abs(spread) > 0.005:
            direction = "高于" if spread > 0 else "低于"
            lines.append(f"历史 VaR {direction} 参数法约 {abs(spread) * 100:.2f} 个百分点，尾部可能厚于正态假设。")
        mc = hi.get("monte_carlo") or {}
        st = mc.get("student_t") or {}
        gbm = mc.get("gbm") or {}
        if st.get("var_pct") and gbm.get("var_pct"):
            t_gap = float(st["var_pct"]) - float(gbm["var_pct"])
            if t_gap > 0.005:
                lines.append(
                    f"蒙特卡洛：Student-t(df≈{st.get('df')}) 99% VaR 高于 GBM 约 {t_gap * 100:.2f} 个百分点，"
                    "厚尾情景下损失可能被正态模型低估。"
                )
    ann_vol = stats.get("annualized_volatility")
    if ann_vol is not None:
        lines.append(f"年化波动约 {ann_vol * 100:.1f}%。")
    return {
        "headline": lines[0] if lines else f"{sym} VaR 报告",
        "bullets": lines[1:],
        "disclaimer": "研究用途，非投资建议；VaR 基于历史收益，不保证未来损失上限。",
    }


def build_portfolio_narrative(report: dict[str, Any]) -> dict[str, Any]:
    lines: list[str] = []
    hi = report.get("metrics", {}).get("0.99") or {}
    gross = report.get("gross_exposure_usdt")
    equity = report.get("account_equity_usdt")
    if hi and gross:
        lines.append(
            f"组合总敞口 {gross} USDT，99% 历史 VaR 约 {hi.get('var_usdt')} USDT"
            + (f"（占权益 {float(hi.get('var_usdt', 0)) / equity * 100:.1f}%）" if equity else "")
            + "。"
        )
    div = report.get("diversification_ratio")
    if div is not None:
        if div > 1.1:
            lines.append(f"分散化比 {div}：成分简单加总 VaR 高于组合 VaR，持仓相关性带来分散效应。")
        elif div < 0.95:
            lines.append(f"分散化比 {div}：组合 VaR 高于简单加总，空头/对冲结构可能放大尾部风险。")
    return {
        "headline": lines[0] if lines else "组合 VaR 报告",
        "bullets": lines[1:],
        "disclaimer": "研究用途，非投资建议。",
    }


def fetch_ohlcv_df(
    symbol: str,
    *,
    timeframe: str = "1d",
    limit: int = 500,
) -> pd.DataFrame:
    return cxt.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)


def _close_series(df: pd.DataFrame) -> pd.Series:
    if "date" in df.columns:
        close = df.set_index("date")["close"]
    else:
        close = df["close"]
    return close.astype(float)


def build_symbol_var_report(
    symbol: str,
    *,
    notional_usdt: float,
    lookback_bars: int = 252,
    confidence_levels: list[float] | None = None,
    horizon_days: int = 1,
    timeframe: str = "1d",
    mc_n_sims: int = DEFAULT_MC_SIMS,
    mc_seed: int = 42,
) -> dict[str, Any]:
    confidence_levels = confidence_levels or [0.95, 0.99]
    df = fetch_ohlcv_df(symbol=symbol, timeframe=timeframe, limit=lookback_bars + 1)
    close = _close_series(df)
    rets = returns_from_close(close)
    latest_price = float(close.iloc[-1])
    effective_notional = float(notional_usdt) if float(notional_usdt) > 0 else latest_price

    stats = summarize_returns(rets)
    metrics = _metrics_block(
        rets,
        notional_usdt=effective_notional,
        confidence_levels=confidence_levels,
        horizon_days=horizon_days,
        mc_n_sims=mc_n_sims,
        mc_seed=mc_seed,
    )

    report = {
        "symbol": symbol.upper(),
        "method": "historical_simulation",
        "params": {
            "lookback_bars": lookback_bars,
            "horizon_days": horizon_days,
            "confidence_levels": confidence_levels,
            "timeframe": timeframe,
            "mc_n_sims": min(max(int(mc_n_sims), 1000), 100_000),
            "mc_seed": mc_seed,
        },
        "notional_usdt": effective_notional,
        "latest_price": latest_price,
        "observations": int(len(rets)),
        "return_stats": stats,
        "return_histogram": return_histogram(rets),
        "stress_scenarios": stress_scenarios(effective_notional),
        "metrics": metrics,
    }
    report["narrative"] = build_symbol_narrative(report, stats=stats)
    return report


def build_portfolio_returns(
    weights: dict[str, float],
    rets_map: dict[str, pd.Series],
) -> pd.Series:
    if not weights or not rets_map:
        return pd.Series(dtype=float)
    frames = []
    for sym, w in weights.items():
        if sym not in rets_map:
            continue
        frames.append(rets_map[sym].rename(sym) * float(w))
    if not frames:
        return pd.Series(dtype=float)
    aligned = pd.concat(frames, axis=1, join="inner")
    return aligned.sum(axis=1)


def _perp_exchange(*, testnet: bool = False):
    if not (settings.binance_api_key and settings.binance_api_secret):
        return None
    return cxt.create_exchange(
        "binance",
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        testnet=testnet or settings.binance_testnet,
        api_base=settings.binance_api_base,
        http_proxy=settings.http_proxy,
        https_proxy=settings.https_proxy,
        market_type="future",
    )


def _base_from_symbol(symbol: str) -> str:
    s = str(symbol or "").strip()
    if not s:
        return ""
    if "/" in s:
        return s.split("/")[0].upper()
    if s.endswith("USDT") and len(s) > 4:
        return s[: -4].upper()
    return s.upper()


def _position_notional_usdt(pos: dict[str, Any]) -> float:
    info = pos.get("info") if isinstance(pos.get("info"), dict) else {}
    notional = pos.get("notional")
    if notional is None and isinstance(info, dict):
        notional = info.get("notional")
    if notional is not None and notional != "":
        return abs(float(notional))

    contracts = pos.get("contracts")
    if contracts is None:
        contracts = pos.get("positionAmt")
    if contracts is None and isinstance(info, dict):
        contracts = info.get("positionAmt")
    contracts_f = float(contracts or 0.0)

    mark = pos.get("markPrice")
    if mark is None and isinstance(info, dict):
        mark = info.get("markPrice")
    if mark is not None and mark != "":
        return abs(contracts_f * float(mark))

    entry = pos.get("entryPrice")
    if entry is None and isinstance(info, dict):
        entry = info.get("entryPrice")
    if entry is not None and entry != "":
        return abs(contracts_f * float(entry))
    return 0.0


def _normalize_position_row(pos: dict[str, Any]) -> dict[str, Any] | None:
    info = pos.get("info") if isinstance(pos.get("info"), dict) else {}
    contracts = pos.get("contracts")
    if contracts is None:
        contracts = pos.get("positionAmt")
    if contracts is None and isinstance(info, dict):
        contracts = info.get("positionAmt")
    amt_f = float(contracts or 0.0)
    if abs(amt_f) <= 1e-12:
        return None

    side = "long" if amt_f > 0 else "short"
    symbol = str(pos.get("symbol") or "")
    base = _base_from_symbol(symbol)
    notional = _position_notional_usdt(pos)
    signed = notional if side == "long" else -notional
    return {
        "base": base,
        "side": side,
        "symbol": symbol,
        "contracts": abs(amt_f),
        "notional_usdt": round(notional, 4),
        "signed_notional_usdt": round(signed, 4),
    }


def fetch_all_open_positions(*, testnet: bool = False) -> list[dict[str, Any]]:
    ex = _perp_exchange(testnet=testnet)
    if ex is None:
        return []
    try:
        try:
            if getattr(ex, "load_time_difference", None):
                ex.load_time_difference()
        except Exception:
            pass
        rows = ex.fetch_positions(None, {"type": "future"})  # type: ignore[attr-defined]
    except Exception:
        rows = []
    finally:
        try:
            ex.close()
        except Exception:
            pass

    out: list[dict[str, Any]] = []
    for pos in rows or []:
        if not isinstance(pos, dict):
            continue
        norm = _normalize_position_row(pos)
        if norm:
            out.append(norm)
    return out


def _returns_map_for_bases(
    bases: list[str],
    *,
    timeframe: str,
    lookback_bars: int,
) -> dict[str, pd.Series]:
    rets_map: dict[str, pd.Series] = {}
    for base in bases:
        df = fetch_ohlcv_df(base, timeframe=timeframe, limit=lookback_bars + 1)
        close = _close_series(df)
        s = returns_from_close(close)
        s.name = base
        rets_map[base] = s
    return rets_map


def _account_equity_usdt(*, testnet: bool) -> float | None:
    from quant_rd_tool.perp_account_analytics import fetch_future_balances

    bal = fetch_future_balances(testnet=testnet)
    if not bal.get("enabled"):
        return None
    summary = bal.get("summary") or {}
    for key in ("totalMarginBalance", "totalWalletBalance"):
        v = summary.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def build_portfolio_var_report(
    *,
    testnet: bool = False,
    timeframe: str = "1d",
    lookback_bars: int = 252,
    horizon_days: int = 1,
    confidence_levels: list[float] | None = None,
    mc_n_sims: int = DEFAULT_MC_SIMS,
    mc_seed: int = 42,
) -> dict[str, Any]:
    confidence_levels = confidence_levels or [0.95, 0.99]

    if not (settings.binance_api_key and settings.binance_api_secret):
        return {
            "enabled": False,
            "error": "missing api key/secret",
            "positions": [],
            "metrics": None,
        }

    positions = fetch_all_open_positions(testnet=testnet)
    if not positions:
        return {
            "enabled": True,
            "positions": [],
            "metrics": None,
            "message": "no open positions",
            "params": {
                "lookback_bars": lookback_bars,
                "horizon_days": horizon_days,
                "confidence_levels": confidence_levels,
                "timeframe": timeframe,
                "testnet": testnet,
            },
        }

    gross = sum(abs(p["signed_notional_usdt"]) for p in positions)
    net = sum(p["signed_notional_usdt"] for p in positions)
    if gross <= 0:
        return {
            "enabled": True,
            "positions": positions,
            "metrics": None,
            "message": "no open positions",
            "gross_exposure_usdt": 0.0,
            "net_exposure_usdt": 0.0,
        }

    weights = {p["base"]: p["signed_notional_usdt"] / gross for p in positions}
    bases = list(weights.keys())
    rets_map = _returns_map_for_bases(bases, timeframe=timeframe, lookback_bars=lookback_bars)
    port_rets = build_portfolio_returns(weights, rets_map)

    metrics = _metrics_block(
        port_rets,
        notional_usdt=gross,
        confidence_levels=confidence_levels,
        horizon_days=horizon_days,
        mc_n_sims=mc_n_sims,
        mc_seed=mc_seed,
    )
    individual_vars: dict[str, float] = {}
    hi_conf = max(confidence_levels)

    for p in positions:
        base = p["base"]
        if base not in rets_map:
            continue
        sym_var = compute_historical_var(rets_map[base], confidence=hi_conf, horizon_days=horizon_days)
        individual_vars[base] = abs(p["signed_notional_usdt"]) * sym_var

    hi_key = confidence_key(hi_conf)
    portfolio_var_usdt = metrics[hi_key]["var_usdt"]
    div_ratio = None
    if portfolio_var_usdt > 0:
        div_ratio = round(sum(individual_vars.values()) / portfolio_var_usdt, 4)

    sum_indiv = sum(individual_vars.values()) or 1.0
    pos_out = []
    for p in positions:
        base = p["base"]
        contrib = individual_vars.get(base, 0.0)
        pos_out.append(
            {
                **p,
                "weight": round(weights.get(base, 0.0), 6),
                "standalone_var_usdt": round(contrib, 4),
                "var_contribution_usdt": round(portfolio_var_usdt * contrib / sum_indiv, 4),
                "var_contribution_pct": round(100 * contrib / sum_indiv, 2),
            }
        )

    equity = _account_equity_usdt(testnet=testnet)
    report = {
        "enabled": True,
        "method": "historical_simulation",
        "params": {
            "lookback_bars": lookback_bars,
            "horizon_days": horizon_days,
            "confidence_levels": confidence_levels,
            "timeframe": timeframe,
            "testnet": testnet,
            "mc_n_sims": min(max(int(mc_n_sims), 1000), 100_000),
            "mc_seed": mc_seed,
        },
        "positions": pos_out,
        "gross_exposure_usdt": round(gross, 4),
        "net_exposure_usdt": round(net, 4),
        "account_equity_usdt": equity,
        "var_pct_of_equity": round(portfolio_var_usdt / equity, 6) if equity and equity > 0 else None,
        "diversification_ratio": div_ratio,
        "observations": int(len(port_rets.dropna())),
        "return_stats": summarize_returns(port_rets),
        "correlation": correlation_matrix(rets_map),
        "stress_scenarios": stress_scenarios(gross),
        "metrics": metrics,
    }
    report["narrative"] = build_portfolio_narrative(report)
    return report


def build_symbol_var_history(
    symbol: str,
    *,
    window: int = 60,
    confidence: float = 0.99,
    lookback_bars: int = 252,
    horizon_days: int = 1,
    timeframe: str = "1d",
    notional_usdt: float = 0.0,
) -> dict[str, Any]:
    total_limit = lookback_bars + window + 1
    df = fetch_ohlcv_df(symbol=symbol, timeframe=timeframe, limit=total_limit)
    close = _close_series(df)
    rets = returns_from_close(close)
    latest_price = float(close.iloc[-1])
    effective_notional = float(notional_usdt) if float(notional_usdt) > 0 else latest_price

    series: list[dict[str, Any]] = []
    end_indices = range(max(0, len(rets) - window), len(rets))
    for i in end_indices:
        window_rets = rets.iloc[max(0, i - lookback_bars + 1) : i + 1]
        if len(window_rets.dropna()) < MIN_OBSERVATIONS:
            continue
        var_pct = compute_historical_var(window_rets, confidence=confidence, horizon_days=horizon_days)
        actual_ret = float(rets.iloc[i])
        date_val = rets.index[i]
        if hasattr(date_val, "isoformat"):
            date_str = date_val.isoformat()  # type: ignore[union-attr]
        else:
            date_str = str(date_val)
        series.append(
            {
                "date": date_str,
                "var_pct": var_pct,
                "var_usdt": round(effective_notional * var_pct, 4),
                "actual_return": round(actual_ret, 6),
                "breach": bool(actual_ret < -var_pct),
            }
        )

    return {
        "symbol": symbol.upper(),
        "confidence": confidence,
        "window": window,
        "lookback_bars": lookback_bars,
        "notional_usdt": effective_notional,
        "breach_count": sum(1 for s in series if s.get("breach")),
        "series": series,
    }
