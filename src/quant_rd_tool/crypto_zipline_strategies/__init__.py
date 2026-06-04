"""Built-in strategy registry for crypto zipline lab."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from quant_rd_tool.crypto_zipline_strategies import signals as sig

StrategyRunner = Callable[[pd.DataFrame, dict[str, Any], float], dict[str, Any]]


def _compute_rsi_series(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _run_with_target_col(
    df: pd.DataFrame,
    target: pd.Series,
    *,
    capital_base: float,
    warmup: int,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_pandas import run_bar_backtest

    work = df.copy()
    work["target"] = target.fillna(0.0).astype(float)
    return run_bar_backtest(work, capital_base=capital_base, warmup=warmup)


def run_ma_crossover(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    fast = int(params.get("fast", 10))
    slow = int(params.get("slow", 30))
    work = df.copy()
    work["fast_ma"] = work["close"].rolling(fast).mean()
    work["slow_ma"] = work["close"].rolling(slow).mean()
    target = pd.Series(0.0, index=work.index)
    target[work["fast_ma"] > work["slow_ma"]] = 1.0
    return _run_with_target_col(work, target, capital_base=capital_base, warmup=slow + 1)


def run_ema_trend(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    work = df.copy()
    work["fast_ema"] = work["close"].ewm(span=fast, adjust=False).mean()
    work["slow_ema"] = work["close"].ewm(span=slow, adjust=False).mean()
    target = pd.Series(0.0, index=work.index)
    target[work["fast_ema"] > work["slow_ema"]] = 1.0
    return _run_with_target_col(work, target, capital_base=capital_base, warmup=slow + 1)


def run_momentum_rsi(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    period = int(params.get("period", 14))
    oversold = float(params.get("oversold", 30))
    overbought = float(params.get("overbought", 70))
    work = df.copy()
    work["rsi"] = _compute_rsi_series(work["close"], period)
    target = pd.Series(0.0, index=work.index)
    target[work["rsi"] < oversold] = 1.0
    target[work["rsi"] > overbought] = 0.0
    target = target.ffill().fillna(0.0)
    return _run_with_target_col(work, target, capital_base=capital_base, warmup=period + 2)


def run_bollinger_revert(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    period = int(params.get("period", 20))
    std_mult = float(params.get("std_mult", 2.0))
    work = df.copy()
    mid = work["close"].rolling(period).mean()
    std = work["close"].rolling(period).std()
    lower = mid - std_mult * std
    upper = mid + std_mult * std
    target = pd.Series(0.0, index=work.index)
    target[work["close"] <= lower] = 1.0
    target[work["close"] >= upper] = 0.0
    target = target.ffill().fillna(0.0)
    return _run_with_target_col(work, target, capital_base=capital_base, warmup=period + 1)


def run_donchian_breakout(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    channel = int(params.get("channel", 20))
    work = df.copy()
    high = work["high"].rolling(channel).max().shift(1)
    low = work["low"].rolling(channel).min().shift(1)
    target = pd.Series(0.0, index=work.index)
    target[work["close"] >= high] = 1.0
    target[work["close"] <= low] = 0.0
    return _run_with_target_col(work, target, capital_base=capital_base, warmup=channel + 2)


def run_macd_cross(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    signal = int(params.get("signal", 9))
    work = df.copy()
    ema_fast = work["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = work["close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    target = pd.Series(0.0, index=work.index)
    target[macd > macd_signal] = 1.0
    return _run_with_target_col(work, target, capital_base=capital_base, warmup=slow + signal + 2)


def _run_signal_strategy(
    df: pd.DataFrame,
    strategy_id: str,
    params: dict[str, Any],
    capital_base: float,
    *,
    warmup: int,
) -> dict[str, Any]:
    n = len(df)
    targets = [0.0] * n
    closes: list[float] = []
    volumes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    last_target = 0.0
    vols = df["volume"].tolist() if "volume" in df.columns else [0.0] * n
    for i in range(n):
        closes.append(float(df["close"].iloc[i]))
        volumes.append(float(vols[i]))
        highs.append(float(df["high"].iloc[i]) if "high" in df.columns else closes[-1])
        lows.append(float(df["low"].iloc[i]) if "low" in df.columns else closes[-1])
        t = sig.signal_for_strategy(
            strategy_id,
            closes,
            volumes,
            params,
            highs=highs,
            lows=lows,
            last_target=last_target,
        )
        if t is not None:
            targets[i] = t
            last_target = t
        else:
            targets[i] = last_target
    work = df.copy()
    target = pd.Series(targets, index=work.index)
    work["target"] = target
    return _run_with_target_col(work, target, capital_base=capital_base, warmup=warmup)


def run_supertrend(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    atr_len = int(params.get("atr_len", 10))
    return _run_signal_strategy(
        df, "supertrend", params, capital_base, warmup=atr_len + 15
    )


def run_supertrend_sized(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    atr_len = int(params.get("atr_len", 10))
    return _run_signal_strategy(
        df, "supertrend_sized", params, capital_base, warmup=atr_len + 15
    )


def run_stoch_rsi(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    need = (
        int(params.get("rsi_period", 14))
        + int(params.get("stoch_period", 14))
        + int(params.get("k_smooth", 3))
        + int(params.get("d_smooth", 3))
        + 5
    )
    return _run_signal_strategy(df, "stoch_rsi", params, capital_base, warmup=need)


def run_golden_cross(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    slow = int(params.get("slow", 200))
    return _run_signal_strategy(df, "golden_cross", params, capital_base, warmup=slow + 5)


def run_ema_rsi_filter(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    slow = int(params.get("slow", 26))
    return _run_signal_strategy(df, "ema_rsi_filter", params, capital_base, warmup=slow + 20)


def run_macd_rsi_confirm(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    slow = int(params.get("slow", 26))
    signal = int(params.get("signal", 9))
    return _run_signal_strategy(
        df, "macd_rsi_confirm", params, capital_base, warmup=slow + signal + 20
    )


def run_volume_breakout(df: pd.DataFrame, params: dict[str, Any], capital_base: float) -> dict[str, Any]:
    lookback = int(params.get("lookback", 20))
    vol_mult = float(params.get("vol_mult", 1.5))
    work = df.copy()
    if "volume" not in work.columns:
        raise ValueError("volume column required for volume_breakout")
    prev_high = work["high"].rolling(lookback).max().shift(1)
    prev_low = work["low"].rolling(lookback).min().shift(1)
    avg_vol = work["volume"].rolling(lookback).mean()
    target = pd.Series(0.0, index=work.index)
    breakout = (work["close"] > prev_high) & (work["volume"] >= avg_vol * vol_mult)
    breakdown = work["close"] < prev_low
    target[breakout] = 1.0
    target[breakdown] = 0.0
    return _run_with_target_col(work, target, capital_base=capital_base, warmup=lookback + 2)


STRATEGY_REGISTRY: dict[str, dict[str, Any]] = {
    "ma_crossover": {
        "id": "ma_crossover",
        "name": "均线交叉",
        "description": "SMA 快线上穿慢线做多，下穿空仓",
        "default_params": {"fast": 10, "slow": 30},
        "min_bars": 35,
        "runner": run_ma_crossover,
    },
    "ema_trend": {
        "id": "ema_trend",
        "name": "EMA 趋势",
        "description": "EMA 快线高于慢线持多，否则空仓",
        "default_params": {"fast": 12, "slow": 26},
        "min_bars": 30,
        "runner": run_ema_trend,
    },
    "momentum_rsi": {
        "id": "momentum_rsi",
        "name": "RSI 动量",
        "description": "RSI 超卖做多、超买平仓，区间内保持仓位",
        "default_params": {"period": 14, "oversold": 30, "overbought": 70},
        "min_bars": 20,
        "runner": run_momentum_rsi,
    },
    "bollinger_revert": {
        "id": "bollinger_revert",
        "name": "布林带回归",
        "description": "触及下轨做多、上轨平仓，中轨区间保持",
        "default_params": {"period": 20, "std_mult": 2.0},
        "min_bars": 25,
        "runner": run_bollinger_revert,
    },
    "donchian_breakout": {
        "id": "donchian_breakout",
        "name": "唐奇安突破",
        "description": "突破 N 日高点做多，跌破 N 日低点平仓",
        "default_params": {"channel": 20},
        "min_bars": 25,
        "runner": run_donchian_breakout,
    },
    "macd_cross": {
        "id": "macd_cross",
        "name": "MACD 交叉",
        "description": "MACD 线上穿信号线做多，下穿空仓",
        "default_params": {"fast": 12, "slow": 26, "signal": 9},
        "min_bars": 40,
        "runner": run_macd_cross,
    },
    "volume_breakout": {
        "id": "volume_breakout",
        "name": "放量突破",
        "description": "价格突破前高且成交量放大时做多",
        "default_params": {"lookback": 20, "vol_mult": 1.5},
        "min_bars": 25,
        "runner": run_volume_breakout,
    },
    "supertrend": {
        "id": "supertrend",
        "name": "Supertrend",
        "description": "TradingView 经典趋势：价格在 Supertrend 线上方 100% 做多，下方空仓",
        "default_params": {"atr_len": 10, "factor": 3.0},
        "min_bars": 30,
        "runner": run_supertrend,
    },
    "supertrend_sized": {
        "id": "supertrend_sized",
        "name": "Supertrend 仓位版",
        "description": "同 Supertrend 信号，按价格距趋势线 ATR 倍数动态仓位（默认最高 50%）",
        "default_params": {
            "atr_len": 10,
            "factor": 3.0,
            "max_position": 0.5,
            "min_position": 0.15,
            "dist_atr": 2.0,
        },
        "min_bars": 30,
        "runner": run_supertrend_sized,
    },
    "stoch_rsi": {
        "id": "stoch_rsi",
        "name": "Stochastic RSI",
        "description": "TV 热门震荡指标：超卖区 K 上穿 D 做多，超买平仓",
        "default_params": {
            "rsi_period": 14,
            "stoch_period": 14,
            "k_smooth": 3,
            "d_smooth": 3,
            "oversold": 20,
            "overbought": 80,
        },
        "min_bars": 40,
        "runner": run_stoch_rsi,
    },
    "golden_cross": {
        "id": "golden_cross",
        "name": "金叉 50/200",
        "description": "TradingView 经典：SMA50 高于 SMA200 持多，否则空仓",
        "default_params": {"fast": 50, "slow": 200},
        "min_bars": 210,
        "runner": run_golden_cross,
    },
    "ema_rsi_filter": {
        "id": "ema_rsi_filter",
        "name": "EMA + RSI 过滤",
        "description": "TV 组合范式：EMA 多头趋势且 RSI 处于 45–75 动量区间",
        "default_params": {"fast": 12, "slow": 26, "rsi_period": 14, "rsi_min": 45, "rsi_max": 75},
        "min_bars": 40,
        "runner": run_ema_rsi_filter,
    },
    "macd_rsi_confirm": {
        "id": "macd_rsi_confirm",
        "name": "MACD + RSI 确认",
        "description": "TV 加权策略常见组合：MACD 金叉且 RSI 50–70 区间确认动量",
        "default_params": {
            "fast": 12,
            "slow": 26,
            "signal": 9,
            "rsi_period": 14,
            "rsi_floor": 50,
            "rsi_cap": 70,
        },
        "min_bars": 45,
        "runner": run_macd_rsi_confirm,
    },
    "adx_trend": {
        "id": "adx_trend",
        "name": "ADX 趋势",
        "description": "TV DMI/ADX：ADX≥25 且 DI+>DI- 时做多，过滤震荡",
        "default_params": {"period": 14, "adx_threshold": 25},
        "min_bars": 35,
        "runner": lambda df, p, c: _run_signal_strategy(
            df, "adx_trend", p, c, warmup=int(p.get("period", 14)) + 20
        ),
    },
    "psar_trend": {
        "id": "psar_trend",
        "name": "Parabolic SAR",
        "description": "TV 内置抛物线 SAR：点在价格下方持多",
        "default_params": {"step": 0.02, "max_step": 0.2},
        "min_bars": 30,
        "runner": lambda df, p, c: _run_signal_strategy(df, "psar_trend", p, c, warmup=25),
    },
    "keltner_breakout": {
        "id": "keltner_breakout",
        "name": "Keltner 突破",
        "description": "TV 社区常用：突破 Keltner 上轨做多，跌破下轨平仓",
        "default_params": {"period": 20, "atr_mult": 1.5},
        "min_bars": 30,
        "runner": lambda df, p, c: _run_signal_strategy(
            df, "keltner_breakout", p, c, warmup=int(p.get("period", 20)) + 10
        ),
    },
    "bb_squeeze": {
        "id": "bb_squeeze",
        "name": "BB Squeeze 突破",
        "description": "TV 热门 Squeeze：布林带带宽压缩后向上突破做多",
        "default_params": {
            "bb_period": 20,
            "bb_std": 2.0,
            "squeeze_lookback": 120,
            "bw_percentile": 20,
        },
        "min_bars": 130,
        "runner": lambda df, p, c: _run_signal_strategy(
            df,
            "bb_squeeze",
            p,
            c,
            warmup=int(p.get("squeeze_lookback", 120)) + int(p.get("bb_period", 20)) + 5,
        ),
    },
    "ichimoku_cloud": {
        "id": "ichimoku_cloud",
        "name": "一目均衡表",
        "description": "TV Ichimoku 简化：价格在云上且转换线>基准线持多",
        "default_params": {"tenkan": 9, "kijun": 26},
        "min_bars": 35,
        "runner": lambda df, p, c: _run_signal_strategy(
            df, "ichimoku_cloud", p, c, warmup=int(p.get("kijun", 26)) + 10
        ),
    },
    "vwap_trend": {
        "id": "vwap_trend",
        "name": "VWAP 趋势",
        "description": "TV 短线常用：收盘价在滚动 VWAP 上方持多",
        "default_params": {"lookback": 20},
        "min_bars": 25,
        "runner": lambda df, p, c: _run_signal_strategy(
            df, "vwap_trend", p, c, warmup=int(p.get("lookback", 20)) + 5
        ),
    },
}


def list_strategies() -> list[dict[str, Any]]:
    out = []
    for spec in STRATEGY_REGISTRY.values():
        out.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "description": spec["description"],
                "default_params": dict(spec["default_params"]),
                "min_bars": spec["min_bars"],
            }
        )
    return out


def get_strategy(strategy_id: str) -> dict[str, Any] | None:
    return STRATEGY_REGISTRY.get(strategy_id)


def get_runner(strategy_id: str) -> StrategyRunner | None:
    spec = STRATEGY_REGISTRY.get(strategy_id)
    if not spec:
        return None
    return spec["runner"]
