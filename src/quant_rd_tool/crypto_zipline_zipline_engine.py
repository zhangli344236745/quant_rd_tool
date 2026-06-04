"""zipline-reloaded backtest engine (minimal imports for subprocess worker)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_zipline_bundle import (
    configure_zipline_env,
    ensure_bundle_ingested,
    load_ohlcv_window,
)
from quant_rd_tool.crypto_zipline_combo import combo_min_bars, normalize_combo_spec
from quant_rd_tool.crypto_zipline_storage import DISCLAIMER
from quant_rd_tool.crypto_zipline_strategies import get_strategy
from quant_rd_tool.crypto_zipline_strategies.zipline_algos import build_zipline_algo
from quant_rd_tool.crypto_zipline_timeframes import (
    DEFAULT_TIMEFRAME,
    bar_minutes_for,
    bundle_name_for,
    normalize_timeframe,
)

MAX_EQUITY_POINTS = 500


def _bar_timestamps(df: pd.DataFrame) -> pd.Series:
    if "timestamp" in df.columns:
        return pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return pd.to_datetime(df["date"], utc=True)


def _slice_bars_for_backtest(
    df: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    warmup_bars: int,
) -> pd.DataFrame:
    ts = _bar_timestamps(df).dt.tz_localize(None)
    start_naive = start.tz_localize(None) if getattr(start, "tzinfo", None) else start
    end_naive = end.tz_localize(None) if getattr(end, "tzinfo", None) else end
    in_range = (ts >= start_naive) & (ts <= end_naive)
    if not in_range.any():
        raise ValueError(f"No bars between {start} and {end}")
    first_idx = int(in_range.to_numpy().argmax())
    start_pos = max(0, first_idx - warmup_bars)
    out = df.iloc[start_pos:].copy()
    out_ts = _bar_timestamps(out).dt.tz_localize(None)
    return out[out_ts <= end_naive].reset_index(drop=True)


def _extract_perf(perf: Any, *, capital_base: float, bar_minutes: int) -> dict[str, Any]:
    equities: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    metrics = {"total_return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "trade_count": 0}

    if perf is None:
        return {"metrics": metrics, "equity_curve": equities, "trades": trades}

    if hasattr(perf, "portfolio_value"):
        pv = perf.portfolio_value.dropna()
        if len(pv) > 0:
            final_val = float(pv.iloc[-1])
            metrics["total_return"] = round((final_val - capital_base) / capital_base, 6)

            idx = pd.to_datetime(pv.index, utc=True)
            pv_series = pd.Series(pv.values, index=idx)
            pv_bars = pv_series.resample(f"{bar_minutes}min").last().dropna()
            if len(pv_bars) < 2:
                pv_bars = pv_series

            rets = pv_bars.pct_change().dropna()
            if len(rets) > 1 and rets.std() > 1e-12:
                metrics["sharpe"] = round(float(rets.mean() / rets.std() * (len(rets) ** 0.5)), 4)

            peak = pv_bars.cummax()
            metrics["max_drawdown"] = round(float(((pv_bars - peak) / peak.replace(0, pd.NA)).min()), 6)

            step = max(1, len(pv_bars) // MAX_EQUITY_POINTS)
            for ts, val in pv_bars.iloc[::step].items():
                equities.append({"time": str(ts), "value": round(float(val), 2)})

    if hasattr(perf, "transactions") and perf.transactions is not None:
        try:
            tx = perf.transactions.dropna()
            for dt, items in tx.items():
                if not items:
                    continue
                for item in items if isinstance(items, (list, tuple)) else [items]:
                    amount = float(item.get("amount", 0))
                    price = float(item.get("price", 0))
                    trades.append(
                        {
                            "time": str(dt),
                            "side": "buy" if amount > 0 else "sell",
                            "price": price,
                            "shares": abs(amount),
                            "value": abs(price * amount),
                        }
                    )
        except Exception:
            pass

    if not trades and hasattr(perf, "orders") and perf.orders is not None:
        try:
            orders = perf.orders.dropna()
            for dt, items in orders.items():
                if not items:
                    continue
                for item in items if isinstance(items, (list, tuple)) else [items]:
                    amount = float(item.get("amount", 0))
                    if abs(amount) < 1e-12:
                        continue
                    price = float(item.get("filled", item.get("limit", 0)) or 0)
                    trades.append(
                        {
                            "time": str(dt),
                            "side": "buy" if amount > 0 else "sell",
                            "price": price,
                            "shares": abs(amount),
                            "value": abs(price * amount),
                        }
                    )
        except Exception:
            pass

    metrics["trade_count"] = len(trades)

    return {"metrics": metrics, "equity_curve": equities, "trades": trades}


def _final_signal_from_perf(perf: Any, asset_name: str) -> dict[str, Any]:
    position = "flat"
    target = 0.0
    bar_time = ""
    if perf is not None and hasattr(perf, "positions") and len(perf.positions):
        try:
            last_pos = perf.positions.iloc[-1]
            if asset_name in last_pos.index:
                amt = float(last_pos[asset_name])
                if amt > 0:
                    position = "long"
                    target = 1.0
        except Exception:
            pass
    if hasattr(perf, "portfolio_value") and len(perf.portfolio_value):
        bar_time = str(perf.portfolio_value.index[-1])
    return {"position": position, "target_pct": target, "bar_time": bar_time}


def _session_start_for_zipline(first_bar: pd.Timestamp, user_start: pd.Timestamp) -> pd.Timestamp:
    """Zipline sessions are midnight; avoid starting before the asset's first minute bar."""
    sess = max(user_start.normalize(), first_bar.normalize())
    if sess < first_bar:
        sess = (first_bar + pd.Timedelta(days=1)).normalize()
    return sess


def run_zipline_backtest_inprocess(
    *,
    symbol: str,
    data_dir: str,
    strategy_id: str,
    strategy_params: dict[str, Any] | None,
    capital_base: float,
    start: str,
    end: str,
    lookback_days: int = 90,
    force_reingest: bool = False,
    timeframe: str = DEFAULT_TIMEFRAME,
    combo_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bundle ingest + zipline.utils.run_algo.run_algorithm."""
    tf = normalize_timeframe(timeframe)
    bar_mins = bar_minutes_for(tf)
    bundle = bundle_name_for(tf)

    combo: dict[str, Any] | None = None
    if combo_spec:
        if "legs" in combo_spec and isinstance(combo_spec.get("legs"), list):
            combo = normalize_combo_spec(legs=combo_spec["legs"], mode=combo_spec.get("mode", "vote"))
        else:
            combo = combo_spec
        warmup = combo_min_bars(combo)
        algo_params: dict[str, Any] = combo
    else:
        strat = get_strategy(strategy_id)
        if not strat:
            raise ValueError(f"Unknown strategy: {strategy_id}")
        algo_params = {**strat["default_params"], **(strategy_params or {})}
        warmup = int(strat.get("min_bars", 20)) + 5

    df = load_ohlcv_window(
        symbol,
        data_dir=data_dir,
        timeframe=tf,
        lookback_days=lookback_days,
        range_start=start,
        range_end=end,
    )
    asset_name = cxt.to_qlib_code(symbol)
    configure_zipline_env(data_dir)

    start_ts = pd.Timestamp(start, tz="UTC").tz_convert("UTC").tz_localize(None)
    end_ts = pd.Timestamp(end, tz="UTC").tz_convert("UTC").tz_localize(None)
    df = _slice_bars_for_backtest(df, start=start_ts, end=end_ts, warmup_bars=warmup)
    if df.empty:
        raise ValueError("No OHLCV bars in backtest window after warmup slice")
    bar_ts = _bar_timestamps(df).dt.tz_localize(None)
    if not ((bar_ts >= start_ts) & (bar_ts <= end_ts)).any():
        raise ValueError(
            f"No bars between {start} and {end} (data: {bar_ts.min()} – {bar_ts.max()})"
        )
    data_start = bar_ts.min()
    data_end = bar_ts.max()
    effective_start = _session_start_for_zipline(data_start, start_ts)
    effective_end = min(end_ts.normalize(), data_end.normalize())
    ingest_meta = ensure_bundle_ingested(
        symbol,
        df,
        data_dir=data_dir,
        timeframe=tf,
        start=data_start.normalize(),
        end=data_end.normalize(),
        force=force_reingest,
    )

    if combo:
        initialize, handle_data = build_zipline_algo(
            asset_name, combo_spec=combo, params=combo
        )
    else:
        initialize, handle_data = build_zipline_algo(
            asset_name, strategy_id=strategy_id, params=algo_params
        )

    from zipline.utils.run_algo import run_algorithm

    perf = run_algorithm(
        start=effective_start,
        end=effective_end,
        initialize=initialize,
        handle_data=handle_data,
        capital_base=capital_base,
        bundle=bundle,
        data_frequency="minute",
    )

    extracted = _extract_perf(perf, capital_base=capital_base, bar_minutes=bar_mins)
    final_signal = _final_signal_from_perf(perf, asset_name)

    out: dict[str, Any] = {
        "engine": "zipline",
        "metrics": extracted["metrics"],
        "trades": extracted["trades"],
        "equity_curve": extracted["equity_curve"],
        "final_signal": final_signal,
        "strategy_params": algo_params,
        "disclaimer": DISCLAIMER,
        "bundle": bundle,
        "asset": asset_name,
        "timeframe": tf,
        "bar_minutes": bar_mins,
        "bar_count": len(df),
        "backtest_start": str(effective_start),
        "backtest_end": str(effective_end),
        **ingest_meta,
    }
    if combo:
        out["combo_mode"] = combo["mode"]
        out["combo_legs"] = combo["legs"]
    return out
