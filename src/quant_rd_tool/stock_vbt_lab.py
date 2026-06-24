"""A-share VectorBT lab — data load, backtest orchestration, persistence."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_rd_tool.market_data import fetch_stock_daily
from quant_rd_tool.stock_ashare_pandas import ashare_backtest_context, run_ashare_bar_backtest
from quant_rd_tool.stock_codes import to_qlib_code
from quant_rd_tool.stock_storage import csv_path, load_csv, save_csv, stock_root, write_meta
from quant_rd_tool.stock_vbt_reports import build_report_artifacts, equity_to_returns
from quant_rd_tool.stock_vbt_strategies import build_target_series, get_strategy, validate_params

VBT_LAB_DIR = Path("data/stocks/vbt_lab")
DEFAULT_DATA_DIR = "data/stocks"


from quant_rd_tool.time_util import to_beijing_iso


def _iso_now(now: datetime | None = None) -> str:
    return to_beijing_iso(now)


def _runs_index_path() -> Path:
    return VBT_LAB_DIR / "runs.jsonl"


def _append_run_index(entry: dict[str, Any]) -> None:
    VBT_LAB_DIR.mkdir(parents=True, exist_ok=True)
    with _runs_index_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_ohlcv(
    symbol: str,
    start: str,
    end: str,
    *,
    data_dir: str = DEFAULT_DATA_DIR,
    refresh: bool = False,
) -> pd.DataFrame:
    code = to_qlib_code(symbol)
    root = stock_root(data_dir, symbol)
    path = csv_path(root)
    if refresh or not path.is_file():
        df = fetch_stock_daily(symbol, start_date=start, end_date=end)
        if "symbol" not in df.columns:
            df = df.copy()
            df["symbol"] = code
        save_csv(df, path)
        write_meta(root, {"symbol": code, "source": "akshare", "start": start, "end": end})
    else:
        df = load_csv(path)
    if df.empty:
        raise ValueError(f"no OHLCV data for {symbol}")
    ts = pd.to_datetime(df["date"])
    mask = (ts >= pd.Timestamp(start)) & (ts <= pd.Timestamp(end))
    out = df.loc[mask].copy()
    if out.empty:
        raise ValueError(f"no bars for {symbol} between {start} and {end}")
    return out.reset_index(drop=True)


def refresh_universe_data(
    symbols: list[str],
    start: str,
    end: str,
    *,
    data_dir: str = DEFAULT_DATA_DIR,
) -> dict[str, Any]:
    """Pull latest AkShare daily bars for each symbol into local cache."""
    refreshed: list[str] = []
    errors: list[dict[str, str]] = []
    for sym in symbols:
        try:
            load_ohlcv(sym, start, end, data_dir=data_dir, refresh=True)
            refreshed.append(to_qlib_code(sym))
        except Exception as e:  # noqa: BLE001 - collect per-symbol errors
            errors.append({"symbol": str(sym), "error": str(e)})
    return {"refreshed": refreshed, "errors": errors}


def evaluate_backtest_on_df(
    df: pd.DataFrame,
    *,
    symbol: str,
    strategy_id: str,
    strategy_params: dict[str, Any] | None = None,
    capital_base: float = 100_000.0,
) -> dict[str, Any]:
    """Run backtest on a prepared OHLCV frame without persisting artifacts."""
    spec = get_strategy(strategy_id)
    params = validate_params(strategy_id, strategy_params)
    min_bars = int(spec["min_bars"])
    if len(df) < min_bars:
        raise ValueError(f"need at least {min_bars} bars, got {len(df)}")

    work = build_target_series(df, strategy_id, params)
    code = to_qlib_code(symbol)
    with ashare_backtest_context(symbol=code, use_ashare=True):
        bt = run_ashare_bar_backtest(
            work,
            capital_base=capital_base,
            warmup=min_bars,
            target_col="target",
            symbol=code,
        )

    equity_curve = bt.get("equity_curve", [])
    returns = equity_to_returns(equity_curve)
    from quant_rd_tool.stock_vbt_reports import extract_metrics

    qs_metrics = extract_metrics(returns)
    return {
        "symbol": code,
        "strategy_id": strategy_id,
        "strategy_params": params,
        "metrics": {**qs_metrics, "engine": bt.get("metrics", {})},
        "execution_stats": bt.get("cost_summary", {}),
        "equity_curve": equity_curve,
        "trades": bt.get("trades", []),
    }


def run_backtest(
    *,
    symbol: str,
    start: str,
    end: str,
    strategy_id: str,
    strategy_params: dict[str, Any] | None = None,
    capital_base: float = 100_000.0,
    data_dir: str = DEFAULT_DATA_DIR,
    refresh_data: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    spec = get_strategy(strategy_id)
    params = validate_params(strategy_id, strategy_params)
    df = load_ohlcv(symbol, start, end, data_dir=data_dir, refresh=refresh_data)
    min_bars = int(spec["min_bars"])
    if len(df) < min_bars:
        raise ValueError(f"need at least {min_bars} bars, got {len(df)}")

    bt_result = evaluate_backtest_on_df(
        df,
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_params=params,
        capital_base=capital_base,
    )
    equity_curve = bt_result["equity_curve"]
    trades = bt_result["trades"]
    qs_metrics = {k: v for k, v in bt_result["metrics"].items() if k != "engine"}
    engine_metrics = bt_result["metrics"].get("engine", {})

    run_id = str(uuid.uuid4())
    run_dir = VBT_LAB_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    params_doc = {
        "run_id": run_id,
        "symbol": bt_result["symbol"],
        "start": start,
        "end": end,
        "strategy_id": strategy_id,
        "strategy_params": params,
        "capital_base": capital_base,
        "created_at": _iso_now(now),
    }
    (run_dir / "params.json").write_text(
        json.dumps(params_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    returns = equity_to_returns(equity_curve)
    report = build_report_artifacts(
        returns,
        run_dir,
        title=f"{bt_result['symbol']} · {spec['name']}",
    )
    metrics = {**report["metrics"], "engine": engine_metrics}
    (run_dir / "equity_curve.json").write_text(
        json.dumps(equity_curve, ensure_ascii=False), encoding="utf-8"
    )
    with (run_dir / "trades.jsonl").open("w", encoding="utf-8") as f:
        for tr in trades:
            f.write(json.dumps(tr, ensure_ascii=False) + "\n")
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = {
        "run_id": run_id,
        "symbol": bt_result["symbol"],
        "strategy_id": strategy_id,
        "strategy_name": spec["name"],
        "start": start,
        "end": end,
        "created_at": params_doc["created_at"],
        "total_return": qs_metrics.get("total_return"),
        "sharpe": qs_metrics.get("sharpe"),
        "max_drawdown": qs_metrics.get("max_drawdown"),
    }
    _append_run_index(summary)

    return {
        "run_id": run_id,
        "symbol": bt_result["symbol"],
        "strategy_id": strategy_id,
        "strategy_name": spec["name"],
        "params": params_doc,
        "metrics": metrics,
        "execution_stats": bt_result["execution_stats"],
        "trades_count": len(trades),
        "equity_curve": equity_curve,
        "trades": trades,
    }


def list_runs(*, limit: int = 20, symbol: str | None = None) -> list[dict[str, Any]]:
    path = _runs_index_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    sym = to_qlib_code(symbol).upper() if symbol else None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if sym and str(row.get("symbol", "")).upper() != sym:
            continue
        rows.append(row)
    return list(reversed(rows[-limit:]))


def get_run(run_id: str) -> dict[str, Any]:
    run_dir = VBT_LAB_DIR / run_id
    if not run_dir.is_dir():
        raise ValueError(f"run not found: {run_id}")
    params = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    equity = json.loads((run_dir / "equity_curve.json").read_text(encoding="utf-8"))
    trades: list[dict[str, Any]] = []
    trades_path = run_dir / "trades.jsonl"
    if trades_path.is_file():
        for line in trades_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                trades.append(json.loads(line))
    return {
        "run_id": run_id,
        "params": params,
        "metrics": metrics,
        "equity_curve": equity,
        "trades": trades,
    }
