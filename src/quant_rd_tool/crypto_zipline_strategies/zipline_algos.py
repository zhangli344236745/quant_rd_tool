"""Zipline initialize/handle_data — bar-aligned via history, combo support."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from quant_rd_tool.crypto_zipline_combo import combo_min_bars, combo_target_from_context
from quant_rd_tool.crypto_zipline_strategies import get_strategy
from quant_rd_tool.crypto_zipline_strategies.signals import signal_for_strategy


def _read_bar(
    data: Any, asset: Any, *, bar_freq: str = "1m"
) -> tuple[float | None, float | None, float | None, Any]:
    try:
        close_h = data.history(asset, "close", 1, bar_freq)
        if close_h is None or len(close_h) == 0:
            close_h = data.history(asset, "price", 1, bar_freq)
        if close_h is None or len(close_h) == 0:
            return None, None, None, None
        close = float(close_h.iloc[-1])
        if close != close:
            return None, None, None, None
        high, low = close, close
        try:
            h = data.history(asset, "high", 1, bar_freq)
            if h is not None and len(h):
                high = float(h.iloc[-1])
        except Exception:
            pass
        try:
            l = data.history(asset, "low", 1, bar_freq)
            if l is not None and len(l):
                low = float(l.iloc[-1])
        except Exception:
            pass
        return close, high, low, close_h.index[-1]
    except Exception:
        pass
    try:
        from zipline.api import get_datetime

        close = float(data.current(asset, "price"))
        if close != close:
            return None, None, None, None
        return close, close, close, get_datetime()
    except Exception:
        return None, None, None, None


def _append_bar(
    context: Any,
    close: float,
    high: float,
    low: float,
    bar_dt: Any,
    *,
    max_len: int,
) -> bool:
    last_dt = getattr(context, "last_bar_dt", None)
    if last_dt is not None and bar_dt == last_dt:
        return False
    context.last_bar_dt = bar_dt
    closes: list[float] = getattr(context, "closes", [])
    highs: list[float] = getattr(context, "highs", [])
    lows: list[float] = getattr(context, "lows", [])
    closes.append(close)
    highs.append(high)
    lows.append(low)
    if len(closes) > max_len:
        closes = closes[-max_len:]
        highs = highs[-max_len:]
        lows = lows[-max_len:]
    context.closes = closes
    context.highs = highs
    context.lows = lows
    volumes: list[float] = getattr(context, "volumes", [])
    try:
        vol = float(getattr(context, "_pending_volume", 0.0))
    except Exception:
        vol = 0.0
    volumes.append(vol)
    if len(volumes) > max_len:
        volumes = volumes[-max_len:]
    context.volumes = volumes
    return True


def _apply_target(context: Any, asset: Any, target: float) -> None:
    from zipline.api import order_target_percent

    last = getattr(context, "last_target", None)
    if last is not None and abs(target - last) < 1e-9:
        return
    order_target_percent(asset, target)
    context.last_target = target


def _setup_commission(context: Any) -> None:
    try:
        from zipline.api import set_commission
        from zipline.finance.commission import PerShare

        set_commission(PerShare(cost=0.0))
    except Exception:
        pass


def _bar_dt_to_epoch_ms(bar_dt: Any) -> int:
    ts = pd.Timestamp(bar_dt)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.value // 1_000_000)


def _compute_target(context: Any) -> float | None:
    lookup = getattr(context, "target_lookup", None)
    bar_dt = getattr(context, "last_bar_dt", None)
    if lookup is not None and bar_dt is not None:
        key = _bar_dt_to_epoch_ms(bar_dt)
        if key in lookup:
            return float(lookup[key])
        # fallback: match nearest bar within 1 minute (zipline vs CSV timestamp drift)
        for delta_ms in (0, -60_000, 60_000, -900_000, 900_000):
            if key + delta_ms in lookup:
                return float(lookup[key + delta_ms])
        last_target = float(getattr(context, "last_target", 0.0) or 0.0)
        return last_target

    closes: list[float] = context.closes
    volumes: list[float] = getattr(context, "volumes", [])
    last_target = float(getattr(context, "last_target", 0.0) or 0.0)
    combo_spec = getattr(context, "combo_spec", None)
    highs = getattr(context, "highs", closes)
    lows = getattr(context, "lows", closes)
    if combo_spec:
        return combo_target_from_context(
            combo_spec, closes, volumes, last_target, highs=highs, lows=lows
        )
    return signal_for_strategy(
        context.strategy_id,
        closes,
        volumes,
        context.params,
        highs=highs,
        lows=lows,
        last_target=last_target,
    )


def _max_history_len(context: Any) -> int:
    combo_spec = getattr(context, "combo_spec", None)
    if combo_spec:
        return combo_min_bars(combo_spec)
    params = context.params
    sid = context.strategy_id
    if sid == "ma_crossover" or sid == "ema_trend":
        return int(params["slow"]) + 10
    if sid == "momentum_rsi":
        return int(params["period"]) + 15
    if sid == "bollinger_revert":
        return int(params["period"]) + 10
    if sid == "donchian_breakout":
        return int(params["channel"]) + 10
    if sid == "macd_cross":
        return int(params["slow"]) + int(params["signal"]) + 15
    if sid == "volume_breakout":
        return int(params["lookback"]) + 10
    if sid == "supertrend" or sid == "supertrend_sized":
        return int(params.get("atr_len", 10)) + 15
    if sid == "stoch_rsi":
        return (
            int(params.get("rsi_period", 14))
            + int(params.get("stoch_period", 14))
            + int(params.get("k_smooth", 3))
            + int(params.get("d_smooth", 3))
            + 10
        )
    if sid == "golden_cross":
        return int(params.get("slow", 200)) + 10
    if sid == "ema_rsi_filter":
        return int(params["slow"]) + int(params.get("rsi_period", 14)) + 10
    if sid == "macd_rsi_confirm":
        return int(params.get("slow", 26)) + int(params.get("signal", 9)) + 20
    if sid == "adx_trend":
        return int(params.get("period", 14)) + 25
    if sid == "psar_trend":
        return 30
    if sid == "keltner_breakout":
        return int(params.get("period", 20)) + 15
    if sid == "bb_squeeze":
        return int(params.get("squeeze_lookback", 120)) + int(params.get("bb_period", 20)) + 10
    if sid == "ichimoku_cloud":
        return int(params.get("kijun", 26)) + 15
    if sid == "vwap_trend":
        return int(params.get("lookback", 20)) + 10
    return 50


def build_zipline_algo(
    asset_name: str,
    *,
    strategy_id: str = "",
    params: dict[str, Any] | None = None,
    combo_spec: dict[str, Any] | None = None,
    bar_freq: str = "1m",
    precomputed_targets: dict[int, float] | None = None,
) -> tuple[Callable[..., None], Callable[..., None]]:
    if combo_spec is None and not strategy_id:
        raise ValueError("strategy_id or combo_spec required")
    if combo_spec is None:
        spec = get_strategy(strategy_id)
        if not spec:
            raise ValueError(f"Unknown strategy: {strategy_id}")
        merged = {**spec["default_params"], **(params or {})}
    else:
        merged = params or {}
        strategy_id = "combo"

    def initialize(context):
        from zipline.api import symbol as zsymbol

        _setup_commission(context)
        context.asset = zsymbol(asset_name)
        context.strategy_id = strategy_id
        context.params = merged
        context.combo_spec = combo_spec
        context.bar_freq = bar_freq
        context.closes = []
        context.highs = []
        context.lows = []
        context.volumes = []
        context.last_bar_dt = None
        context.last_target = None
        context._pending_volume = 0.0
        context.target_lookup = precomputed_targets

    def handle_data(context, data):
        from zipline.api import record

        asset = context.asset
        try:
            bar_freq = getattr(context, "bar_freq", "1m")
            vol_hist = data.history(asset, "volume", 1, bar_freq)
            if vol_hist is not None and len(vol_hist):
                context._pending_volume = float(vol_hist.iloc[-1])
        except Exception:
            context._pending_volume = 0.0

        bar_freq = getattr(context, "bar_freq", "1m")
        close, high, low, bar_dt = _read_bar(data, asset, bar_freq=bar_freq)
        if close is None or bar_dt is None:
            return
        max_len = _max_history_len(context)
        if not _append_bar(context, close, high or close, low or close, bar_dt, max_len=max_len):
            return

        target = _compute_target(context)
        if target is None:
            return

        _apply_target(context, asset, target)
        record(price=close, target=target)

    return initialize, handle_data
