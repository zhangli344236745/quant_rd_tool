"""A-share zipline-reloaded backtest (daily bars, XSHG calendar)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_rd_tool.stock_codes import to_qlib_code
from quant_rd_tool.crypto_zipline_combo import combo_min_bars, normalize_combo_spec
from quant_rd_tool.crypto_zipline_storage import DISCLAIMER
from quant_rd_tool.crypto_zipline_strategies import get_strategy
from quant_rd_tool.crypto_zipline_strategies.zipline_algos import build_zipline_algo
from quant_rd_tool.crypto_zipline_zipline_engine import (
    _bar_timestamps,
    _extract_perf,
    _final_signal_from_perf,
    _prepare_ml_zipline_targets,
    _session_start_for_zipline,
    _slice_bars_for_backtest,
)
from quant_rd_tool.stock_zipline_strategies import is_stock_strategy
from quant_rd_tool.stock_zipline_bundle import (
    configure_zipline_env,
    ensure_bundle_ingested,
    load_ohlcv_window,
)
from quant_rd_tool.stock_zipline_timeframes import (
    DEFAULT_TIMEFRAME,
    bar_minutes_for,
    bundle_name_for,
    effective_ml_train_bars,
    normalize_timeframe,
)

ZIPLINE_BAR_FREQ = "1d"


def run_zipline_backtest_inprocess(
    *,
    symbol: str,
    data_dir: str,
    strategy_id: str,
    strategy_params: dict[str, Any] | None,
    capital_base: float,
    start: str,
    end: str,
    lookback_days: int = 365,
    force_reingest: bool = False,
    timeframe: str = DEFAULT_TIMEFRAME,
    combo_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tf = normalize_timeframe(timeframe)
    bar_mins = bar_minutes_for(tf)
    bundle = bundle_name_for(tf)

    combo: dict[str, Any] | None = None
    ml_metrics: dict[str, Any] | None = None
    target_lookup: dict[int, float] | None = None
    is_ml = False
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
        if not is_stock_strategy(strategy_id):
            raise ValueError(f"Strategy {strategy_id} is not available for A-share lab")
        algo_params = {**strat["default_params"], **(strategy_params or {})}
        warmup = int(strat.get("min_bars", 20)) + 5
        is_ml = strategy_id.startswith("xgb_")
        if is_ml:
            warmup = max(
                warmup,
                effective_ml_train_bars(tf, int(algo_params.get("train_bars", 2000))) + 5,
            )

    df = load_ohlcv_window(
        symbol,
        data_dir=data_dir,
        timeframe=tf,
        lookback_days=lookback_days,
        range_start=start,
        range_end=end,
    )
    asset_name = to_qlib_code(symbol)
    configure_zipline_env(data_dir)

    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
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

    if is_ml and not combo:
        target_lookup, ml_metrics = _prepare_ml_zipline_targets(
            df,
            strategy_id=strategy_id,
            algo_params=algo_params,
            timeframe=tf,
        )

    if combo:
        initialize, handle_data = build_zipline_algo(
            asset_name, combo_spec=combo, params=combo, bar_freq=ZIPLINE_BAR_FREQ
        )
    else:
        initialize, handle_data = build_zipline_algo(
            asset_name,
            strategy_id=strategy_id,
            params=algo_params,
            precomputed_targets=target_lookup,
            bar_freq=ZIPLINE_BAR_FREQ,
        )

    from zipline.utils.run_algo import run_algorithm

    perf = run_algorithm(
        start=effective_start,
        end=effective_end,
        initialize=initialize,
        handle_data=handle_data,
        capital_base=capital_base,
        bundle=bundle,
        data_frequency="daily",
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
        "market": "stock",
        **ingest_meta,
    }
    if combo:
        out["combo_mode"] = combo["mode"]
        out["combo_legs"] = combo["legs"]
    if ml_metrics:
        out["ml_metrics"] = ml_metrics
    return out
