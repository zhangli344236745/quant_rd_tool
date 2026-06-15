"""A-share VaR / CVaR on daily OHLCV (reuses crypto_var math)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from quant_rd_tool import market_data as mkt
from quant_rd_tool.akshare_data import to_ak_code, to_qlib_code
from quant_rd_tool.crypto_var import (
    DEFAULT_MC_SIMS,
    MIN_OBSERVATIONS,
    _metrics_block,
    build_portfolio_returns,
    compute_historical_var,
    confidence_key,
    correlation_matrix,
    return_histogram,
    returns_from_close,
    stress_scenarios,
    summarize_returns,
)
from quant_rd_tool.stock_storage import csv_path, load_csv, save_csv, stock_root, write_meta

DEFAULT_DATA_DIR = "data/stocks"


def _close_series(df: pd.DataFrame) -> pd.Series:
    if "date" in df.columns:
        close = df.set_index("date")["close"]
    else:
        close = df["close"]
    return close.astype(float)


def _remap_metrics_to_cny(metrics: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, m in metrics.items():
        row: dict[str, Any] = {
            "var_pct": m["var_pct"],
            "cvar_pct": m["cvar_pct"],
            "var_cny": m["var_usdt"],
            "cvar_cny": m["cvar_usdt"],
            "parametric_var_pct": m.get("parametric_var_pct"),
            "parametric_var_cny": m.get("parametric_var_usdt"),
            "method_spread_pct": m.get("method_spread_pct"),
            "backtest": m.get("backtest"),
        }
        mc = m.get("monte_carlo")
        if mc:
            gbm = dict(mc["gbm"])
            st = dict(mc["student_t"])
            gbm["var_cny"] = gbm.pop("var_usdt", None)
            gbm["cvar_cny"] = gbm.pop("cvar_usdt", None)
            st["var_cny"] = st.pop("var_usdt", None)
            st["cvar_cny"] = st.pop("cvar_usdt", None)
            row["monte_carlo"] = {**mc, "gbm": gbm, "student_t": st}
        else:
            row["monte_carlo"] = None
        out[key] = row
    return out


def _remap_stress_to_cny(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "shock_pct": r["shock_pct"],
            "loss_pct": r["loss_pct"],
            "loss_cny": r["loss_usdt"],
        }
        for r in rows
    ]


def fetch_ohlcv_df(
    symbol: str,
    *,
    data_dir: str = DEFAULT_DATA_DIR,
    limit: int = 500,
    refresh: bool = False,
) -> pd.DataFrame:
    """Load local daily OHLCV or fetch via akshare when missing."""
    code = to_ak_code(symbol)
    root = stock_root(data_dir, code)
    path = csv_path(root)

    if not refresh and path.is_file():
        df = load_csv(path)
        if len(df) >= MIN_OBSERVATIONS + 1:
            return df.tail(limit + 1).reset_index(drop=True)

    backfill_days = max(400, int(limit * 1.6))
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=backfill_days)).isoformat()
    df = mkt.fetch_stock_daily(code, start_date=start_date, end_date=end_date)
    root.mkdir(parents=True, exist_ok=True)
    save_csv(df, path)
    write_meta(
        root,
        {
            "symbol": to_qlib_code(code),
            "start_date": start_date,
            "end_date": end_date,
            "source": "var_fetch",
            "bars": len(df),
        },
    )
    return df.tail(limit + 1).reset_index(drop=True)


def _returns_map_for_codes(
    codes: list[str],
    *,
    data_dir: str,
    lookback_bars: int,
) -> dict[str, pd.Series]:
    rets_map: dict[str, pd.Series] = {}
    for code in codes:
        df = fetch_ohlcv_df(code, data_dir=data_dir, limit=lookback_bars + 1)
        close = _close_series(df)
        s = returns_from_close(close)
        s.name = code
        rets_map[code] = s
    return rets_map


def _latest_price_for_code(symbol: str, *, data_dir: str) -> float:
    df = fetch_ohlcv_df(symbol, data_dir=data_dir, limit=5)
    return float(_close_series(df).iloc[-1])


def normalize_holdings(
    holdings: list[dict[str, Any]],
    *,
    data_dir: str = DEFAULT_DATA_DIR,
) -> list[dict[str, Any]]:
    """Resolve notional_cny from shares when needed."""
    out: list[dict[str, Any]] = []
    for row in holdings:
        sym = str(row.get("symbol") or "").strip()
        if not sym:
            continue
        code = to_ak_code(sym)
        qlib = to_qlib_code(code)
        price = _latest_price_for_code(code, data_dir=data_dir)
        shares = row.get("shares")
        notional = row.get("notional_cny")
        if notional is None and shares is not None:
            notional = float(shares) * price
        if notional is None:
            notional = price * 100.0
        signed = float(notional)
        if shares is not None and float(shares) < 0:
            signed = -abs(signed)
        side = "long" if signed >= 0 else "short"
        out.append(
            {
                "code": code,
                "qlib_code": qlib,
                "side": side,
                "latest_price": round(price, 4),
                "shares": float(shares) if shares is not None else None,
                "notional_cny": round(abs(signed), 4),
                "signed_notional_cny": round(signed, 4),
            }
        )
    return out


def build_symbol_narrative(
    report: dict[str, Any],
    *,
    stats: dict[str, float | None],
) -> dict[str, Any]:
    sym = report.get("symbol", "")
    hi = report.get("metrics", {}).get("0.99") or report.get("metrics", {}).get(
        next(iter(report.get("metrics", {})), "")
    )
    lines: list[str] = []
    if hi:
        lines.append(
            f"{sym} 在 {report.get('params', {}).get('horizon_days', 1)} 日、"
            f"{float(hi.get('var_pct', 0)) * 100:.2f}% 历史 VaR 下，"
            f"名义 {report.get('notional_cny')} 元的预估最大损失约 {hi.get('var_cny')} 元。"
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
                    f"蒙特卡洛：Student-t(df≈{st.get('df')}) 99% VaR 高于 GBM 约 {t_gap * 100:.2f} 个百分点。"
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
    gross = report.get("gross_exposure_cny")
    if hi and gross:
        lines.append(
            f"组合总敞口 {gross} 元，99% 历史 VaR 约 {hi.get('var_cny')} 元。"
        )
    div = report.get("diversification_ratio")
    if div is not None:
        if div > 1.1:
            lines.append(f"分散化比 {div}：成分简单加总 VaR 高于组合 VaR，持仓相关性带来分散效应。")
        elif div < 0.95:
            lines.append(f"分散化比 {div}：组合 VaR 高于简单加总，对冲结构可能放大尾部风险。")
    return {
        "headline": lines[0] if lines else "组合 VaR 报告",
        "bullets": lines[1:],
        "disclaimer": "研究用途，非投资建议。",
    }


def build_symbol_var_report(
    symbol: str,
    *,
    notional_cny: float,
    lookback_bars: int = 252,
    confidence_levels: list[float] | None = None,
    horizon_days: int = 1,
    data_dir: str = DEFAULT_DATA_DIR,
    mc_n_sims: int = DEFAULT_MC_SIMS,
    mc_seed: int = 42,
) -> dict[str, Any]:
    confidence_levels = confidence_levels or [0.95, 0.99]
    code = to_ak_code(symbol)
    qlib = to_qlib_code(code)
    df = fetch_ohlcv_df(code, data_dir=data_dir, limit=lookback_bars + 1)
    close = _close_series(df)
    rets = returns_from_close(close)
    latest_price = float(close.iloc[-1])
    effective_notional = float(notional_cny) if float(notional_cny) > 0 else latest_price * 100.0

    stats = summarize_returns(rets)
    metrics = _remap_metrics_to_cny(
        _metrics_block(
            rets,
            notional_usdt=effective_notional,
            confidence_levels=confidence_levels,
            horizon_days=horizon_days,
            mc_n_sims=mc_n_sims,
            mc_seed=mc_seed,
        )
    )

    report = {
        "market": "stock",
        "symbol": qlib,
        "code": code,
        "method": "historical_simulation",
        "params": {
            "lookback_bars": lookback_bars,
            "horizon_days": horizon_days,
            "confidence_levels": confidence_levels,
            "timeframe": "1d",
            "data_dir": data_dir,
            "mc_n_sims": min(max(int(mc_n_sims), 1000), 100_000),
            "mc_seed": mc_seed,
        },
        "notional_cny": effective_notional,
        "latest_price": latest_price,
        "observations": int(len(rets)),
        "return_stats": stats,
        "return_histogram": return_histogram(rets),
        "stress_scenarios": _remap_stress_to_cny(stress_scenarios(effective_notional)),
        "metrics": metrics,
    }
    report["narrative"] = build_symbol_narrative(report, stats=stats)
    return report


def build_symbol_var_report_from_df(
    df: pd.DataFrame,
    symbol: str,
    *,
    notional_cny: float,
    lookback_bars: int = 252,
    confidence_levels: list[float] | None = None,
    horizon_days: int = 1,
    data_dir: str = DEFAULT_DATA_DIR,
    mc_n_sims: int = DEFAULT_MC_SIMS,
    mc_seed: int = 42,
) -> dict[str, Any]:
    """VaR from an in-memory OHLCV frame (workflow step)."""
    confidence_levels = confidence_levels or [0.95, 0.99]
    code = to_ak_code(symbol)
    qlib = to_qlib_code(code)
    work = df.tail(lookback_bars + 1).copy()
    close = _close_series(work)
    rets = returns_from_close(close)
    latest_price = float(close.iloc[-1])
    effective_notional = float(notional_cny) if float(notional_cny) > 0 else latest_price * 100.0
    stats = summarize_returns(rets)
    metrics = _remap_metrics_to_cny(
        _metrics_block(
            rets,
            notional_usdt=effective_notional,
            confidence_levels=confidence_levels,
            horizon_days=horizon_days,
            mc_n_sims=mc_n_sims,
            mc_seed=mc_seed,
        )
    )
    report = {
        "market": "stock",
        "symbol": qlib,
        "code": code,
        "method": "historical_simulation",
        "params": {
            "lookback_bars": lookback_bars,
            "horizon_days": horizon_days,
            "confidence_levels": confidence_levels,
            "timeframe": "1d",
            "data_dir": data_dir,
            "mc_n_sims": min(max(int(mc_n_sims), 1000), 100_000),
            "mc_seed": mc_seed,
        },
        "notional_cny": effective_notional,
        "latest_price": latest_price,
        "observations": int(len(rets)),
        "return_stats": stats,
        "return_histogram": return_histogram(rets),
        "stress_scenarios": _remap_stress_to_cny(stress_scenarios(effective_notional)),
        "metrics": metrics,
    }
    report["narrative"] = build_symbol_narrative(report, stats=stats)
    return report


def build_portfolio_var_report(
    holdings: list[dict[str, Any]],
    *,
    data_dir: str = DEFAULT_DATA_DIR,
    lookback_bars: int = 252,
    horizon_days: int = 1,
    confidence_levels: list[float] | None = None,
    mc_n_sims: int = DEFAULT_MC_SIMS,
    mc_seed: int = 42,
) -> dict[str, Any]:
    confidence_levels = confidence_levels or [0.95, 0.99]
    positions = normalize_holdings(holdings, data_dir=data_dir)
    if not positions:
        return {
            "enabled": True,
            "market": "stock",
            "positions": [],
            "metrics": None,
            "message": "no holdings",
            "params": {
                "lookback_bars": lookback_bars,
                "horizon_days": horizon_days,
                "confidence_levels": confidence_levels,
                "data_dir": data_dir,
            },
        }

    gross = sum(abs(p["signed_notional_cny"]) for p in positions)
    net = sum(p["signed_notional_cny"] for p in positions)
    if gross <= 0:
        return {
            "enabled": True,
            "market": "stock",
            "positions": positions,
            "metrics": None,
            "message": "no exposure",
            "gross_exposure_cny": 0.0,
            "net_exposure_cny": 0.0,
        }

    weights = {p["code"]: p["signed_notional_cny"] / gross for p in positions}
    codes = list(weights.keys())
    rets_map = _returns_map_for_codes(codes, data_dir=data_dir, lookback_bars=lookback_bars)
    port_rets = build_portfolio_returns(weights, rets_map)

    metrics = _remap_metrics_to_cny(
        _metrics_block(
            port_rets,
            notional_usdt=gross,
            confidence_levels=confidence_levels,
            horizon_days=horizon_days,
            mc_n_sims=mc_n_sims,
            mc_seed=mc_seed,
        )
    )

    hi_conf = max(confidence_levels)
    individual_vars: dict[str, float] = {}
    for p in positions:
        c = p["code"]
        if c not in rets_map:
            continue
        sym_var = compute_historical_var(rets_map[c], confidence=hi_conf, horizon_days=horizon_days)
        individual_vars[c] = abs(p["signed_notional_cny"]) * sym_var

    hi_key = confidence_key(hi_conf)
    portfolio_var_cny = metrics[hi_key]["var_cny"]
    div_ratio = None
    if portfolio_var_cny > 0:
        div_ratio = round(sum(individual_vars.values()) / portfolio_var_cny, 4)

    sum_indiv = sum(individual_vars.values()) or 1.0
    pos_out = []
    for p in positions:
        c = p["code"]
        contrib = individual_vars.get(c, 0.0)
        pos_out.append(
            {
                **p,
                "weight": round(weights.get(c, 0.0), 6),
                "standalone_var_cny": round(contrib, 4),
                "var_contribution_cny": round(portfolio_var_cny * contrib / sum_indiv, 4),
                "var_contribution_pct": round(100 * contrib / sum_indiv, 2),
            }
        )

    report = {
        "enabled": True,
        "market": "stock",
        "method": "historical_simulation",
        "params": {
            "lookback_bars": lookback_bars,
            "horizon_days": horizon_days,
            "confidence_levels": confidence_levels,
            "data_dir": data_dir,
            "mc_n_sims": min(max(int(mc_n_sims), 1000), 100_000),
            "mc_seed": mc_seed,
        },
        "positions": pos_out,
        "gross_exposure_cny": round(gross, 4),
        "net_exposure_cny": round(net, 4),
        "diversification_ratio": div_ratio,
        "observations": int(len(port_rets.dropna())),
        "return_stats": summarize_returns(port_rets),
        "correlation": correlation_matrix(rets_map),
        "stress_scenarios": _remap_stress_to_cny(stress_scenarios(gross)),
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
    notional_cny: float = 0.0,
    data_dir: str = DEFAULT_DATA_DIR,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_var import compute_historical_var as _hist_var

    code = to_ak_code(symbol)
    qlib = to_qlib_code(code)
    total_limit = lookback_bars + window + 1
    df = fetch_ohlcv_df(code, data_dir=data_dir, limit=total_limit)
    close = _close_series(df)
    rets = returns_from_close(close)
    latest_price = float(close.iloc[-1])
    effective_notional = float(notional_cny) if float(notional_cny) > 0 else latest_price * 100.0

    series: list[dict[str, Any]] = []
    end_indices = range(max(0, len(rets) - window), len(rets))
    for i in end_indices:
        window_rets = rets.iloc[max(0, i - lookback_bars + 1) : i + 1]
        if len(window_rets.dropna()) < MIN_OBSERVATIONS:
            continue
        var_pct = _hist_var(window_rets, confidence=confidence, horizon_days=horizon_days)
        actual_ret = float(rets.iloc[i])
        date_val = rets.index[i]
        date_str = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)
        series.append(
            {
                "date": date_str,
                "var_pct": var_pct,
                "var_cny": round(effective_notional * var_pct, 4),
                "actual_return": round(actual_ret, 6),
                "breach": bool(actual_ret < -var_pct),
            }
        )

    return {
        "market": "stock",
        "symbol": qlib,
        "code": code,
        "confidence": confidence,
        "window": window,
        "lookback_bars": lookback_bars,
        "notional_cny": effective_notional,
        "breach_count": sum(1 for s in series if s.get("breach")),
        "series": series,
    }
