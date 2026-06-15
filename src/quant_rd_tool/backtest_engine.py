"""Simple momentum backtest: akshare data → qlib bin dump → pandas Top-K + qlib risk metrics."""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from qlib.contrib.evaluate import risk_analysis

from quant_rd_tool import akshare_data as ak_data
from quant_rd_tool import market_data as mkt
from quant_rd_tool.market_data import DataProvider
from quant_rd_tool.advisor import build_advice
from quant_rd_tool.stock_ashare_execution import (
    AShareBoardRules,
    AShareFeeSchedule,
    execution_rules_payload,
    run_topk_backtest_ashare,
)
from quant_rd_tool.qlib_dump import QlibDataDumper
from quant_rd_tool.qlib_init import init_qlib
from quant_rd_tool.qlib_ml import MlAlgorithm, build_ml_score_panel


def _momentum_panel(frames: dict[str, pd.DataFrame], lookback: int) -> pd.DataFrame:
    """Wide close panel indexed by date, columns = qlib codes."""
    series_list = []
    for code, df in frames.items():
        s = df.set_index(pd.to_datetime(df["date"]))["close"].rename(code)
        series_list.append(s)
    close = pd.concat(series_list, axis=1).sort_index()
    return close / close.shift(lookback) - 1.0


def _topk_backtest(
    scores: pd.DataFrame,
    close: pd.DataFrame,
    *,
    topk: int,
    initial_cash: float,
    open_cost: float = 0.0005,
    close_cost: float = 0.0015,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Daily rebalance: hold equal-weight top-k by prior-day momentum score.
    Returns (daily report, weight history).
    """
    scores = scores.shift(1)
    ret = close.pct_change()
    dates = scores.dropna(how="all").index.intersection(ret.index)
    cash = initial_cash
    holdings: dict[str, float] = {}
    report_rows: list[dict[str, Any]] = []
    weight_rows: list[dict[str, Any]] = []

    for dt in dates:
        row = scores.loc[dt].dropna()
        if row.empty:
            continue
        targets = row.nlargest(min(topk, len(row))).index.tolist()
        prices = close.loc[dt, targets].astype(float)
        port_value = cash + sum(holdings.get(t, 0) * float(close.loc[dt, t]) for t in holdings)
        if port_value <= 0:
            continue

        target_w = 1.0 / len(targets)
        new_holdings: dict[str, float] = {}
        cost = 0.0
        for t in targets:
            px = float(prices[t])
            if px <= 0:
                continue
            desired = port_value * target_w
            old_shares = holdings.get(t, 0.0)
            new_shares = desired / px
            trade_shares = new_shares - old_shares
            trade_val = abs(trade_shares * px)
            fee_rate = open_cost if trade_shares > 0 else close_cost
            cost += trade_val * fee_rate
            new_holdings[t] = new_shares
        for t in list(holdings):
            if t not in new_holdings:
                trade_val = abs(holdings[t] * float(close.loc[dt, t]))
                cost += trade_val * close_cost

        holdings = new_holdings
        cash = max(0.0, cash - cost)
        end_value = cash + sum(holdings.get(t, 0) * float(close.loc[dt, t]) for t in holdings)
        prev_value = report_rows[-1]["portfolio_value"] if report_rows else initial_cash
        daily_ret = end_value / prev_value - 1 if prev_value else 0.0
        report_rows.append(
            {
                "date": dt,
                "return": daily_ret,
                "cost": cost / prev_value if prev_value else 0.0,
                "portfolio_value": end_value,
            }
        )
        weight_rows.append(
            {
                "date": dt,
                **{t: holdings.get(t, 0) * float(close.loc[dt, t]) / end_value for t in targets},
            }
        )

    report = pd.DataFrame(report_rows).set_index("date") if report_rows else pd.DataFrame()
    weights = pd.DataFrame(weight_rows).set_index("date") if weight_rows else pd.DataFrame()
    return report, weights


def _benchmark_returns(
    frames: dict[str, pd.DataFrame],
    bench_code: str,
    index: pd.DatetimeIndex,
) -> pd.Series:
    if bench_code in frames:
        s = frames[bench_code].set_index(pd.to_datetime(frames[bench_code]["date"]))["close"]
        return s.reindex(index).pct_change().fillna(0.0)
    return pd.Series(0.0, index=index)


def run_backtest(
    symbols: list[str] | None = None,
    *,
    start_date: str = "2023-01-01",
    end_date: str | None = None,
    lookback: int = 20,
    topk: int = 3,
    n_drop: int = 1,
    initial_cash: float = 1_000_000.0,
    benchmark: str = "sh000300",
    qlib_data_dir: str | Path | None = None,
    refresh_data: bool = True,
    signal_mode: str = "momentum",
    ml_algorithm: MlAlgorithm = "lgb",
    data_provider: DataProvider = "auto",
    use_ashare_rules: bool = True,
    fee_schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    End-to-end: market data → qlib-format dump → Top-K backtest → advice.

    signal_mode: ``momentum`` (default) or ``ml`` (Alpha158 + XGBoost/LightGBM OOS scores).
    data_provider: ``auto`` | ``akshare`` | ``openbb``.
    """
    _ = n_drop
    if signal_mode not in ("momentum", "ml"):
        raise ValueError("signal_mode must be 'momentum' or 'ml'")
    if end_date is None:
        end_date = date.today().isoformat()
    universe = symbols or ak_data.default_demo_universe()
    stock_codes = [ak_data.to_qlib_code(s) for s in universe]

    frames = mkt.fetch_universe(
        universe,
        start_date=start_date,
        end_date=end_date,
        benchmark=benchmark,
        provider=data_provider,
    )
    tradable = {k: v for k, v in frames.items() if k in stock_codes}
    bench_code = "SH000300" if "SH000300" in frames else next(iter(tradable))

    work_dir: Path
    owns_dir = False
    if qlib_data_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="quant_rd_qlib_"))
        owns_dir = True
    else:
        work_dir = Path(qlib_data_dir)
        if refresh_data and work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    try:
        QlibDataDumper(work_dir).dump(frames)
        init_qlib(str(work_dir.resolve()))

        stock_frames = {k: v for k, v in tradable.items()}
        close = pd.concat(
            [
                stock_frames[c].set_index(pd.to_datetime(stock_frames[c]["date"]))["close"].rename(c)
                for c in stock_frames
            ],
            axis=1,
        ).sort_index()

        ml_summary: dict[str, Any] | None = None
        if signal_mode == "ml":
            scores, ml_summary = build_ml_score_panel(
                str(work_dir.resolve()),
                stock_frames,
                start_date=start_date,
                end_date=end_date,
                algorithm=ml_algorithm,
            )
            if scores.empty:
                raise ValueError(
                    "ML 信号生成失败，请扩大日期范围或改用 signal_mode=momentum。"
                )
            warmup = 0
            tk = min(topk, len(stock_frames))
            strategy_desc = f"qlib Alpha158+{ml_algorithm.upper()} OOS Top-{tk} 轮动"
        else:
            scores = _momentum_panel(stock_frames, lookback)
            warmup = lookback + 5
            tk = min(topk, len(stock_frames))
            strategy_desc = f"{lookback}日动量 Top-{tk} 等权轮动"

        close = close.iloc[warmup:]
        scores = scores.reindex(close.index).dropna(how="all")
        close = close.reindex(scores.index).dropna(how="all")
        scores = scores.reindex(close.index)

        topk_eff = min(topk, len(stock_frames))
        fees = AShareFeeSchedule(**fee_schedule) if fee_schedule else AShareFeeSchedule()
        board = AShareBoardRules()
        trades_sample: list[dict[str, Any]] = []
        cost_summary: dict[str, Any] | None = None
        execution_rules: dict[str, Any] | None = None

        if use_ashare_rules:
            report, weights, trades_sample, exec_stats = run_topk_backtest_ashare(
                scores,
                close,
                topk=topk_eff,
                initial_cash=initial_cash,
                fees=fees,
                board=board,
            )
            cost_summary = exec_stats.to_dict()
            execution_rules = execution_rules_payload(fees=fees, board=board)
        else:
            report, weights = _topk_backtest(
                scores,
                close,
                topk=topk_eff,
                initial_cash=initial_cash,
            )
        if not report.empty:
            bench = _benchmark_returns(frames, bench_code, report.index)
            report["bench"] = bench.reindex(report.index).fillna(0.0)

        metrics = _extract_metrics(report)
        latest_holdings = _latest_weights(weights, list(stock_frames))
        latest_scores = _latest_ml_scores(scores, list(stock_frames))
        advice = build_advice(
            metrics=metrics,
            holdings=latest_holdings,
            scores=latest_scores,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
            strategy_desc=strategy_desc,
        )

        openbb_context: dict[str, Any] | None = None
        try:
            from quant_rd_tool.openbb_macro import fetch_macro_context
            from quant_rd_tool.openbb_settings import configure_openbb_credentials

            configure_openbb_credentials()
            macro = fetch_macro_context(use_fred=True)
            if macro.get("available"):
                openbb_context = {"macro_summary": macro.get("summary"), "macro": macro}
        except Exception:
            openbb_context = None

        from quant_rd_tool.research_audit import record_research_run

        audit_record = record_research_run(
            "portfolio_backtest",
            inputs={
                "symbols": symbols,
                "start_date": start_date,
                "end_date": end_date,
                "signal_mode": signal_mode,
                "topk": topk,
                "use_ashare_rules": use_ashare_rules,
            },
            outputs_summary={
                "total_return": metrics.get("total_return"),
                "sharpe": metrics.get("sharpe"),
                "max_drawdown": metrics.get("max_drawdown"),
                "oos_gate_pass_rate": (ml_summary or {}).get("oos_summary", {}).get("gate_pass_rate")
                if ml_summary
                else None,
            },
        )

        return {
            "universe": universe,
            "qlib_codes": sorted(stock_frames),
            "benchmark": bench_code,
            "qlib_data_path": str(work_dir.resolve()),
            "start_date": start_date,
            "end_date": end_date,
            "signal_mode": signal_mode,
            "ml_algorithm": ml_algorithm if signal_mode == "ml" else None,
            "ml_summary": ml_summary,
            "oos_summary": (ml_summary or {}).get("oos_summary") if ml_summary else None,
            "metrics": metrics,
            "holdings": latest_holdings,
            "factor_scores": latest_scores,
            "advice": advice,
            "openbb": openbb_context,
            "report_tail": _report_tail(report),
            "use_ashare_rules": use_ashare_rules,
            "execution_rules": execution_rules,
            "cost_summary": cost_summary,
            "trades_sample": trades_sample[:20] if trades_sample else [],
            "audit_record": audit_record,
        }
    finally:
        if owns_dir and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def _extract_metrics(report: pd.DataFrame) -> dict[str, float | None]:
    if report is None or report.empty or "return" not in report.columns:
        return {}
    ret = report["return"].dropna()
    if ret.empty:
        return {}
    risk = risk_analysis(ret, freq="day")
    bench_excess = report["return"] - report.get("bench", pd.Series(0.0, index=report.index))
    if bench_excess.notna().any():
        excess_risk = risk_analysis(bench_excess.dropna(), freq="day")
    else:
        excess_risk = None

    def _get(series: pd.Series, key: str) -> float | None:
        try:
            val = float(series.loc[key, "risk"])
            return None if np.isnan(val) else round(val, 6)
        except (KeyError, TypeError):
            return None

    out = {
        "total_return": round(float((1 + ret).prod() - 1), 6),
        "annualized_return": _get(risk, "annualized_return"),
        "sharpe_ratio": _get(risk, "information_ratio"),
        "max_drawdown": _get(risk, "max_drawdown"),
        "win_rate": round(float((ret > 0).mean()), 4),
        "trading_days": int(len(ret)),
    }
    if excess_risk is not None:
        out["excess_annualized_return"] = _get(excess_risk, "annualized_return")
    return out


def _report_tail(report: pd.DataFrame, n: int = 10) -> list[dict[str, Any]]:
    if report is None or report.empty:
        return []
    tail = report.tail(n)
    rows = []
    for idx, row in tail.iterrows():
        rows.append(
            {
                "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                "return": round(float(row.get("return", 0)), 6),
                "bench": round(float(row.get("bench", 0)), 6) if "bench" in row else None,
                "cost": round(float(row.get("cost", 0)), 6) if "cost" in row else None,
            }
        )
    return rows


def _latest_weights(weights: pd.DataFrame, instruments: list[str]) -> list[dict[str, Any]]:
    if weights is None or weights.empty:
        return []
    last = weights.iloc[-1]
    rows = []
    for code in instruments:
        if code in last.index and pd.notna(last[code]) and float(last[code]) > 0:
            rows.append({"code": code, "weight": round(float(last[code]), 4)})
    rows.sort(key=lambda x: x["weight"], reverse=True)
    return rows


def _latest_ml_scores(scores: pd.DataFrame, instruments: list[str]) -> list[dict[str, Any]]:
    if scores is None or scores.empty:
        return []
    last = scores.iloc[-1]
    rows = []
    for code in instruments:
        if code in last.index and pd.notna(last[code]):
            rows.append({"code": code, "score": round(float(last[code]), 6)})
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows
