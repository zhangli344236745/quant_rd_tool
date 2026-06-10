"""TradingView-style strategy catalog (50 rule-based strategies)."""

from __future__ import annotations

from typing import Any

# Existing 19 strategies (metadata only; runners live in __init__.py)
_EXISTING: list[dict[str, Any]] = [
    {"id": "ma_crossover", "name": "均线交叉", "description": "SMA 快线上穿慢线做多，下穿空仓", "category": "trend", "tv_ref": "Moving Average Cross", "default_params": {"fast": 10, "slow": 30}, "min_bars": 35},
    {"id": "ema_trend", "name": "EMA 趋势", "description": "EMA 快线高于慢线持多，否则空仓", "category": "trend", "tv_ref": "EMA Cross", "default_params": {"fast": 12, "slow": 26}, "min_bars": 30},
    {"id": "momentum_rsi", "name": "RSI 动量", "description": "RSI 超卖做多、超买平仓", "category": "momentum", "tv_ref": "RSI", "default_params": {"period": 14, "oversold": 30, "overbought": 70}, "min_bars": 20},
    {"id": "bollinger_revert", "name": "布林带回归", "description": "触及下轨做多、上轨平仓", "category": "volatility", "tv_ref": "Bollinger Bands", "default_params": {"period": 20, "std_mult": 2.0}, "min_bars": 25},
    {"id": "donchian_breakout", "name": "唐奇安突破", "description": "突破 N 日高点做多", "category": "trend", "tv_ref": "Donchian Channel", "default_params": {"channel": 20}, "min_bars": 25},
    {"id": "macd_cross", "name": "MACD 交叉", "description": "MACD 线上穿信号线做多", "category": "momentum", "tv_ref": "MACD", "default_params": {"fast": 12, "slow": 26, "signal": 9}, "min_bars": 40},
    {"id": "volume_breakout", "name": "放量突破", "description": "价格突破前高且成交量放大", "category": "volume", "tv_ref": "Volume Breakout", "default_params": {"lookback": 20, "vol_mult": 1.5}, "min_bars": 25},
    {"id": "supertrend", "name": "Supertrend", "description": "价格在 Supertrend 线上方持多", "category": "trend", "tv_ref": "Supertrend", "default_params": {"atr_len": 10, "factor": 3.0}, "min_bars": 30},
    {"id": "supertrend_sized", "name": "Supertrend 仓位版", "description": "Supertrend + ATR 动态仓位", "category": "trend", "tv_ref": "Supertrend", "default_params": {"atr_len": 10, "factor": 3.0, "max_position": 0.5, "min_position": 0.15, "dist_atr": 2.0}, "min_bars": 30},
    {"id": "stoch_rsi", "name": "Stochastic RSI", "description": "Stoch RSI 超卖金叉做多", "category": "momentum", "tv_ref": "Stoch RSI", "default_params": {"rsi_period": 14, "stoch_period": 14, "k_smooth": 3, "d_smooth": 3, "oversold": 20, "overbought": 80}, "min_bars": 40},
    {"id": "golden_cross", "name": "金叉 50/200", "description": "SMA50 高于 SMA200 持多", "category": "trend", "tv_ref": "Golden Cross", "default_params": {"fast": 50, "slow": 200}, "min_bars": 210},
    {"id": "ema_rsi_filter", "name": "EMA + RSI 过滤", "description": "EMA 多头且 RSI 45–75", "category": "combo", "tv_ref": "EMA+RSI", "default_params": {"fast": 12, "slow": 26, "rsi_period": 14, "rsi_min": 45, "rsi_max": 75}, "min_bars": 40},
    {"id": "macd_rsi_confirm", "name": "MACD + RSI 确认", "description": "MACD 金叉且 RSI 50–70", "category": "combo", "tv_ref": "MACD+RSI", "default_params": {"fast": 12, "slow": 26, "signal": 9, "rsi_period": 14, "rsi_floor": 50, "rsi_cap": 70}, "min_bars": 45},
    {"id": "adx_trend", "name": "ADX 趋势", "description": "ADX≥25 且 DI+>DI-", "category": "trend", "tv_ref": "ADX/DMI", "default_params": {"period": 14, "adx_threshold": 25}, "min_bars": 35},
    {"id": "psar_trend", "name": "Parabolic SAR", "description": "SAR 在价下持多", "category": "trend", "tv_ref": "Parabolic SAR", "default_params": {"step": 0.02, "max_step": 0.2}, "min_bars": 30},
    {"id": "keltner_breakout", "name": "Keltner 突破", "description": "突破 Keltner 上轨做多", "category": "volatility", "tv_ref": "Keltner Channels", "default_params": {"period": 20, "atr_mult": 1.5}, "min_bars": 30},
    {"id": "bb_squeeze", "name": "BB Squeeze 突破", "description": "带宽压缩后向上突破", "category": "volatility", "tv_ref": "BB Squeeze", "default_params": {"bb_period": 20, "bb_std": 2.0, "squeeze_lookback": 120, "bw_percentile": 20}, "min_bars": 130},
    {"id": "ichimoku_cloud", "name": "一目均衡表", "description": "价格在云上且转换>基准", "category": "trend", "tv_ref": "Ichimoku", "default_params": {"tenkan": 9, "kijun": 26}, "min_bars": 35},
    {"id": "vwap_trend", "name": "VWAP 趋势", "description": "收盘价在 VWAP 上方持多", "category": "volume", "tv_ref": "VWAP", "default_params": {"lookback": 20}, "min_bars": 25},
]

_NEW: list[dict[str, Any]] = [
    {"id": "hull_ma_trend", "name": "Hull MA 趋势", "description": "价格在 Hull MA 上方持多", "category": "trend", "tv_ref": "Hull MA", "default_params": {"period": 55}, "min_bars": 60},
    {"id": "dema_cross", "name": "DEMA 交叉", "description": "DEMA 快线高于慢线持多", "category": "trend", "tv_ref": "DEMA", "default_params": {"fast": 12, "slow": 26}, "min_bars": 55},
    {"id": "t3_ma_trend", "name": "T3 MA 趋势", "description": "T3 平滑均线趋势", "category": "trend", "tv_ref": "T3 Moving Average", "default_params": {"period": 8, "vfactor": 0.7}, "min_bars": 50},
    {"id": "alma_trend", "name": "ALMA 趋势", "description": "价格在 ALMA 上方持多", "category": "trend", "tv_ref": "ALMA", "default_params": {"period": 9, "offset": 0.85, "sigma": 6.0}, "min_bars": 15},
    {"id": "zero_lag_ema", "name": "Zero Lag EMA", "description": "ZLEMA 趋势跟踪", "category": "trend", "tv_ref": "Zero Lag EMA", "default_params": {"period": 21}, "min_bars": 30},
    {"id": "ssl_channel", "name": "SSL Channel", "description": "SSL 通道多头", "category": "trend", "tv_ref": "SSL Channel", "default_params": {"period": 10}, "min_bars": 15},
    {"id": "chandelier_exit", "name": "Chandelier Exit", "description": "Chandelier 多头止损线之上", "category": "trend", "tv_ref": "Chandelier Exit", "default_params": {"period": 22, "mult": 3.0}, "min_bars": 30},
    {"id": "aroon_trend", "name": "Aroon 趋势", "description": "Aroon Up > Down 且 >50", "category": "trend", "tv_ref": "Aroon", "default_params": {"period": 25}, "min_bars": 30},
    {"id": "linreg_channel", "name": "线性回归通道", "description": "突破 LinReg 上轨做多", "category": "trend", "tv_ref": "Linear Regression", "default_params": {"period": 20, "mult": 2.0}, "min_bars": 25},
    {"id": "williams_r", "name": "Williams %R", "description": "超卖区做多、超买平仓", "category": "momentum", "tv_ref": "Williams %R", "default_params": {"period": 14, "oversold": -80, "overbought": -20}, "min_bars": 20},
    {"id": "cci_revert", "name": "CCI 回归", "description": "CCI 超卖做多", "category": "momentum", "tv_ref": "CCI", "default_params": {"period": 20, "oversold": -100, "overbought": 100}, "min_bars": 25},
    {"id": "tsi_momentum", "name": "TSI 动量", "description": "True Strength Index 金叉", "category": "momentum", "tv_ref": "TSI", "default_params": {"long": 25, "short": 13, "signal": 7}, "min_bars": 50},
    {"id": "ultimate_osc", "name": "Ultimate Oscillator", "description": "UO > 50 持多", "category": "momentum", "tv_ref": "Ultimate Oscillator", "default_params": {"period": 28}, "min_bars": 35},
    {"id": "wavetrend", "name": "WaveTrend", "description": "LazyBear WT 超卖金叉", "category": "momentum", "tv_ref": "WaveTrend [WT]", "default_params": {"channel_len": 10, "avg_len": 21, "ob_level": 60, "os_level": -60}, "min_bars": 40},
    {"id": "fisher_transform", "name": "Fisher Transform", "description": "Fisher 动量转向做多", "category": "momentum", "tv_ref": "Fisher Transform", "default_params": {"period": 10}, "min_bars": 20},
    {"id": "connors_rsi", "name": "Connors RSI", "description": "CRSI 超卖做多", "category": "momentum", "tv_ref": "Connors RSI", "default_params": {"rsi_period": 3, "streak_rsi": 2, "pct_rank": 100}, "min_bars": 110},
    {"id": "rci_trend", "name": "RCI 趋势", "description": "Rank Correlation Index 趋势", "category": "momentum", "tv_ref": "RCI3lines", "default_params": {"period": 9, "threshold": 0}, "min_bars": 15},
    {"id": "coppock_curve", "name": "Coppock Curve", "description": "Coppock 曲线 >0 持多", "category": "momentum", "tv_ref": "Coppock Curve", "default_params": {"wma_period": 10, "roc1": 14, "roc2": 11}, "min_bars": 30},
    {"id": "kst_momentum", "name": "KST 动量", "description": "Know Sure Thing 金叉", "category": "momentum", "tv_ref": "KST", "default_params": {"signal": 9}, "min_bars": 65},
    {"id": "squeeze_momentum", "name": "Squeeze Momentum", "description": "LazyBear SQZMOM 挤压突破", "category": "volatility", "tv_ref": "Squeeze Momentum [LazyBear]", "default_params": {"bb_period": 20, "bb_mult": 2.0, "kc_mult": 1.5}, "min_bars": 30},
    {"id": "keltner_squeeze", "name": "Keltner Squeeze", "description": "BB 在 KC 内压缩后突破", "category": "volatility", "tv_ref": "TTM Squeeze", "default_params": {"period": 20}, "min_bars": 30},
    {"id": "atr_breakout", "name": "ATR 突破", "description": "ATR 通道突破做多", "category": "volatility", "tv_ref": "ATR Channel", "default_params": {"period": 14, "mult": 2.0}, "min_bars": 20},
    {"id": "mfi_revert", "name": "MFI 回归", "description": "Money Flow Index 超卖", "category": "volume", "tv_ref": "MFI", "default_params": {"period": 14, "oversold": 20, "overbought": 80}, "min_bars": 20},
    {"id": "obv_trend", "name": "OBV 趋势", "description": "OBV 高于均线持多", "category": "volume", "tv_ref": "OBV", "default_params": {"period": 20}, "min_bars": 25},
    {"id": "chaikin_mf", "name": "Chaikin MF", "description": "CMF > 0 持多", "category": "volume", "tv_ref": "Chaikin Money Flow", "default_params": {"period": 20}, "min_bars": 25},
    {"id": "vwap_cross", "name": "VWAP 交叉", "description": "价格上穿 VWAP", "category": "volume", "tv_ref": "VWAP Cross", "default_params": {"lookback": 20}, "min_bars": 25},
    {"id": "heikin_ashi_trend", "name": "Heikin Ashi 趋势", "description": "连续 HA 阳线持多", "category": "combo", "tv_ref": "Heikin Ashi", "default_params": {"min_bull": 3}, "min_bars": 10},
    {"id": "elder_impulse", "name": "Elder Impulse", "description": "Elder 脉冲系统多头", "category": "combo", "tv_ref": "Elder Impulse", "default_params": {"ema_period": 13}, "min_bars": 25},
    {"id": "tdi_dynamic", "name": "TDI 动态", "description": "Traders Dynamic Index 多头", "category": "combo", "tv_ref": "TDI", "default_params": {"rsi_period": 13, "band": 34}, "min_bars": 50},
    {"id": "ut_bot", "name": "UT Bot", "description": "UT Bot Alerts 简化版", "category": "combo", "tv_ref": "UT Bot Alerts", "default_params": {"key": 2.0, "atr_period": 10}, "min_bars": 15},
    {"id": "range_filter", "name": "Range Filter", "description": "Range Filter 趋势", "category": "combo", "tv_ref": "Range Filter", "default_params": {"period": 100, "mult": 3.0}, "min_bars": 105},
]

TV_STRATEGIES: list[dict[str, Any]] = _EXISTING + _NEW

ML_STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "xgb_alpha158",
        "name": "XGB Alpha158",
        "description": "Walk-forward XGBoost on Alpha158-style OHLCV features",
        "category": "ml",
        "source": "ml",
        "tv_ref": "Qlib Alpha158 + XGBoost",
        "default_params": {"train_bars": 2000, "retrain_every": 500, "label_horizon": 1, "min_train_samples": 500},
        "min_bars": 2500,
    },
    {
        "id": "xgb_tv_ensemble",
        "name": "XGB TV 集成",
        "description": "XGBoost 元模型：Alpha158 特征 + 50 TV 信号矩阵",
        "category": "ml",
        "source": "ml",
        "tv_ref": "Ensemble",
        "default_params": {"train_bars": 2000, "retrain_every": 500, "label_horizon": 1, "min_train_samples": 500},
        "min_bars": 2500,
    },
    {
        "id": "xgb_tv_filter",
        "name": "XGB TV 过滤",
        "description": "TV 策略信号需 XGB 同向确认",
        "category": "ml",
        "source": "ml",
        "tv_ref": "ML Filter",
        "default_params": {
            "base_strategy": "supertrend",
            "train_bars": 2000,
            "retrain_every": 500,
            "label_horizon": 1,
            "min_train_samples": 500,
        },
        "min_bars": 2500,
    },
]

NEW_TV_IDS: frozenset[str] = frozenset(s["id"] for s in _NEW)


def list_tv_strategies() -> list[dict[str, Any]]:
    out = []
    for spec in TV_STRATEGIES:
        row = dict(spec)
        row.setdefault("source", "tv")
        out.append(row)
    return out


def get_tv_strategy(strategy_id: str) -> dict[str, Any] | None:
    for spec in TV_STRATEGIES:
        if spec["id"] == strategy_id:
            row = dict(spec)
            row.setdefault("source", "tv")
            return row
    return None


def list_ml_strategies() -> list[dict[str, Any]]:
    return [dict(s) for s in ML_STRATEGIES]


def get_ml_strategy(strategy_id: str) -> dict[str, Any] | None:
    for spec in ML_STRATEGIES:
        if spec["id"] == strategy_id:
            return dict(spec)
    return None


def all_strategy_ids() -> list[str]:
    return [s["id"] for s in TV_STRATEGIES] + [s["id"] for s in ML_STRATEGIES]
