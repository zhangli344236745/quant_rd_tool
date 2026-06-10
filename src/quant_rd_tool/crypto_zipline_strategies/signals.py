"""Shared signal logic for pandas + zipline strategy runners."""

from __future__ import annotations

import math
from typing import Any, Callable


def sma(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def ema_last(values: list[float], span: int) -> float | None:
    if len(values) < span:
        return None
    alpha = 2.0 / (span + 1)
    e = values[0]
    for v in values[1:]:
        e = alpha * v + (1 - alpha) * e
    return e


def ma_crossover_target(closes: list[float], *, fast: int, slow: int) -> float | None:
    if len(closes) < slow:
        return None
    window = closes[-slow:]
    fast_ma = sum(window[-fast:]) / fast
    slow_ma = sum(window) / slow
    return 1.0 if fast_ma > slow_ma else 0.0


def ema_crossover_target(closes: list[float], *, fast: int, slow: int) -> float | None:
    if len(closes) < slow:
        return None
    fast_ema = ema_last(closes, fast)
    slow_ema = ema_last(closes, slow)
    if fast_ema is None or slow_ema is None:
        return None
    return 1.0 if fast_ema > slow_ema else 0.0


def rsi_value(closes: list[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    window = closes[-(period + 1) :]
    gains = 0.0
    losses = 0.0
    for i in range(1, len(window)):
        delta = window[i] - window[i - 1]
        if delta > 0:
            gains += delta
        elif delta < 0:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def rsi_target(
    closes: list[float],
    *,
    period: int,
    oversold: float,
    overbought: float,
    last_target: float = 0.0,
) -> float | None:
    rsi = rsi_value(closes, period)
    if rsi is None:
        return None
    if rsi < oversold:
        return 1.0
    if rsi > overbought:
        return 0.0
    return last_target


def bollinger_target(
    closes: list[float],
    *,
    period: int,
    std_mult: float,
    last_target: float = 0.0,
) -> float | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    std = math.sqrt(var) if var > 0 else 0.0
    upper = mean + std_mult * std
    lower = mean - std_mult * std
    price = closes[-1]
    if price <= lower:
        return 1.0
    if price >= upper:
        return 0.0
    return last_target


def donchian_breakout_target(closes: list[float], *, channel: int) -> float | None:
    if len(closes) < channel + 1:
        return None
    window = closes[-(channel + 1) : -1]
    high = max(window)
    low = min(window)
    price = closes[-1]
    if price >= high:
        return 1.0
    if price <= low:
        return 0.0
    return None


def _macd_lines(closes: list[float], *, fast: int, slow: int, signal: int) -> tuple[float | None, float | None]:
    if len(closes) < slow + signal:
        return None, None
    def ema_series(span: int) -> list[float]:
        alpha = 2.0 / (span + 1)
        out: list[float] = []
        e = closes[0]
        out.append(e)
        for v in closes[1:]:
            e = alpha * v + (1 - alpha) * e
            out.append(e)
        return out

    fast_line = ema_series(fast)
    slow_line = ema_series(slow)
    macd_line = [f - s for f, s in zip(fast_line, slow_line, strict=False)]
    sig_alpha = 2.0 / (signal + 1)
    sig = macd_line[0]
    for m in macd_line[1:]:
        sig = sig_alpha * m + (1 - sig_alpha) * sig
    return macd_line[-1], sig


def macd_cross_target(closes: list[float], *, fast: int, slow: int, signal: int) -> float | None:
    macd, sig = _macd_lines(closes, fast=fast, slow=slow, signal=signal)
    if macd is None or sig is None:
        return None
    return 1.0 if macd > sig else 0.0


def volume_breakout_target(
    closes: list[float],
    volumes: list[float],
    *,
    lookback: int,
    vol_mult: float,
) -> float | None:
    if len(closes) < lookback + 1 or len(volumes) < lookback + 1:
        return None
    price = closes[-1]
    prev_high = max(closes[-(lookback + 1) : -1])
    avg_vol = sum(volumes[-lookback:]) / lookback
    if price > prev_high and volumes[-1] >= avg_vol * vol_mult:
        return 1.0
    if price < min(closes[-(lookback + 1) : -1]):
        return 0.0
    return None


def _true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(len(closes)):
        if i == 0:
            out.append(highs[i] - lows[i])
        else:
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            out.append(max(hl, hc, lc))
    return out


def _rma(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    alpha = 1.0 / period
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def _supertrend_snapshot(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    atr_len: int,
    factor: float,
) -> dict[str, float] | None:
    n = len(closes)
    if n < atr_len + 2:
        return None
    tr = _true_range(highs, lows, closes)
    atr_vals = _rma(tr, atr_len)
    if len(atr_vals) < 2:
        return None
    offset = n - len(atr_vals)
    direction = 1
    final_upper = 0.0
    final_lower = 0.0
    last_atr = atr_vals[-1]
    for j, atr in enumerate(atr_vals):
        i = offset + j
        hl2 = (highs[i] + lows[i]) / 2.0
        basic_ub = hl2 + factor * atr
        basic_lb = hl2 - factor * atr
        if j == 0:
            final_upper, final_lower = basic_ub, basic_lb
        else:
            prev_close = closes[i - 1]
            final_upper = (
                basic_ub
                if basic_ub < final_upper or prev_close > final_upper
                else final_upper
            )
            final_lower = (
                basic_lb
                if basic_lb > final_lower or prev_close < final_lower
                else final_lower
            )
        if closes[i] > final_upper:
            direction = 1
        elif closes[i] < final_lower:
            direction = -1
        last_atr = atr
    close = closes[-1]
    line = final_lower if direction == 1 else final_upper
    return {
        "direction": float(direction),
        "close": close,
        "line": line,
        "atr": last_atr,
    }


def supertrend_target(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    atr_len: int = 10,
    factor: float = 3.0,
    last_target: float = 0.0,
) -> float | None:
    """TradingView-style Supertrend: price above line = 100% long, below = flat."""
    snap = _supertrend_snapshot(closes, highs, lows, atr_len=atr_len, factor=factor)
    if snap is None:
        return None
    if snap["direction"] > 0:
        return 1.0
    if snap["direction"] < 0:
        return 0.0
    return last_target


def supertrend_sized_target(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    atr_len: int = 10,
    factor: float = 3.0,
    max_position: float = 0.5,
    min_position: float = 0.15,
    dist_atr: float = 2.0,
    last_target: float = 0.0,
) -> float | None:
    """Supertrend + ATR distance position sizing (caps exposure vs full 100% long)."""
    snap = _supertrend_snapshot(closes, highs, lows, atr_len=atr_len, factor=factor)
    if snap is None:
        return None
    if snap["direction"] < 0:
        return 0.0
    if snap["direction"] <= 0:
        return last_target

    max_pos = max(0.05, min(1.0, max_position))
    min_pos = max(0.0, min(max_pos, min_position))
    atr = snap["atr"]
    if atr <= 1e-12:
        return max_pos
    dist = max(0.0, (snap["close"] - snap["line"]) / atr)
    strength = min(1.0, dist / max(dist_atr, 0.5))
    sized = min_pos + (max_pos - min_pos) * strength
    return round(min(max_pos, max(0.0, sized)), 4)


def _rsi_series(closes: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    for i in range(period, len(closes)):
        window = closes[i - period : i + 1]
        gains = 0.0
        losses = 0.0
        for k in range(1, len(window)):
            delta = window[k] - window[k - 1]
            if delta > 0:
                gains += delta
            elif delta < 0:
                losses -= delta
        avg_loss = losses / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = (gains / period) / avg_loss
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def stoch_rsi_target(
    closes: list[float],
    *,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
    oversold: float = 20.0,
    overbought: float = 80.0,
    last_target: float = 0.0,
) -> float | None:
    """Stochastic RSI: K cross above D in oversold zone long; overbought exit."""
    need = rsi_period + stoch_period + k_smooth + d_smooth + 2
    if len(closes) < need:
        return None
    rsi_vals = [v for v in _rsi_series(closes, rsi_period) if v is not None]
    if len(rsi_vals) < stoch_period + k_smooth + d_smooth:
        return None
    stoch: list[float] = []
    for i in range(stoch_period - 1, len(rsi_vals)):
        seg = rsi_vals[i - stoch_period + 1 : i + 1]
        lo, hi = min(seg), max(seg)
        stoch.append(50.0 if hi == lo else (rsi_vals[i] - lo) / (hi - lo) * 100.0)
    if len(stoch) < k_smooth + d_smooth:
        return None

    def sma(vals: list[float], n: int) -> list[float]:
        out: list[float] = []
        for i in range(n - 1, len(vals)):
            out.append(sum(vals[i - n + 1 : i + 1]) / n)
        return out

    k_line = sma(stoch, k_smooth)
    d_line = sma(k_line, d_smooth)
    if not k_line or not d_line:
        return None
    k, d = k_line[-1], d_line[-1]
    if k > d and k < oversold:
        return 1.0
    if k < d and k > overbought:
        return 0.0
    if k > overbought:
        return 0.0
    return last_target


def golden_cross_target(closes: list[float], *, fast: int = 50, slow: int = 200) -> float | None:
    """Classic 50/200 SMA golden cross (TradingView community staple)."""
    if len(closes) < slow:
        return None
    fast_ma = sum(closes[-fast:]) / fast
    slow_ma = sum(closes[-slow:]) / slow
    return 1.0 if fast_ma > slow_ma else 0.0


def ema_rsi_filter_target(
    closes: list[float],
    *,
    fast: int = 12,
    slow: int = 26,
    rsi_period: int = 14,
    rsi_min: float = 45.0,
    rsi_max: float = 75.0,
) -> float | None:
    """EMA trend + RSI band filter (TV: Supertrend+EMA+RSI style, long-only)."""
    if len(closes) < slow + 2:
        return None
    fast_ema = ema_last(closes, fast)
    slow_ema = ema_last(closes, slow)
    rsi = rsi_value(closes, rsi_period)
    if fast_ema is None or slow_ema is None or rsi is None:
        return None
    if fast_ema > slow_ema and rsi_min <= rsi <= rsi_max:
        return 1.0
    return 0.0


def macd_rsi_confirm_target(
    closes: list[float],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    rsi_period: int = 14,
    rsi_floor: float = 50.0,
    rsi_cap: float = 70.0,
) -> float | None:
    """MACD bullish + RSI momentum window (popular TV combo)."""
    macd, sig = _macd_lines(closes, fast=fast, slow=slow, signal=signal)
    rsi = rsi_value(closes, rsi_period)
    if macd is None or sig is None or rsi is None:
        return None
    if macd > sig and rsi_floor <= rsi <= rsi_cap:
        return 1.0
    return 0.0


def _dmi_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int,
) -> tuple[float | None, float | None, float | None]:
    """Wilder ADX / DI+ / DI- on the full series (returns last bar values)."""
    n = len(closes)
    if n < period + 2:
        return None, None, None
    tr_list: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr_list.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    if len(tr_list) < period:
        return None, None, None

    def wilder_smooth(vals: list[float], p: int) -> list[float]:
        s = sum(vals[:p])
        out = [s]
        for v in vals[p:]:
            s = s - (s / p) + v
            out.append(s)
        return out

    atr_s = wilder_smooth(tr_list, period)
    plus_s = wilder_smooth(plus_dm, period)
    minus_s = wilder_smooth(minus_dm, period)
    di_plus: list[float] = []
    di_minus: list[float] = []
    dx: list[float] = []
    for a, p, m in zip(atr_s, plus_s, minus_s, strict=False):
        if a <= 1e-12:
            di_plus.append(0.0)
            di_minus.append(0.0)
            dx.append(0.0)
            continue
        dip = 100.0 * p / a
        dim = 100.0 * m / a
        di_plus.append(dip)
        di_minus.append(dim)
        denom = dip + dim
        dx.append(100.0 * abs(dip - dim) / denom if denom > 1e-12 else 0.0)
    if len(dx) < period:
        return None, None, None
    adx_vals = wilder_smooth(dx, period)
    return adx_vals[-1], di_plus[-1], di_minus[-1]


def adx_trend_target(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    period: int = 14,
    adx_threshold: float = 25.0,
) -> float | None:
    """TV ADX/DMI: strong trend (ADX>阈值) 且 DI+>DI- 做多."""
    adx, dip, dim = _dmi_adx(highs, lows, closes, period)
    if adx is None or dip is None or dim is None:
        return None
    if adx >= adx_threshold and dip > dim:
        return 1.0
    return 0.0


def psar_trend_target(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    step: float = 0.02,
    max_step: float = 0.2,
) -> float | None:
    """Parabolic SAR (TV built-in): SAR 在价下 = 多头."""
    n = len(closes)
    if n < 3:
        return None
    af = step
    uptrend = closes[1] >= closes[0]
    sar = lows[0] if uptrend else highs[0]
    ep = highs[0] if uptrend else lows[0]
    for i in range(1, n):
        prev_sar = sar
        sar = prev_sar + af * (ep - prev_sar)
        if uptrend:
            sar = min(sar, lows[i - 1], lows[i] if i > 0 else lows[i - 1])
        else:
            sar = max(sar, highs[i - 1], highs[i] if i > 0 else highs[i - 1])
        if uptrend:
            if lows[i] < sar:
                uptrend = False
                sar = ep
                ep = lows[i]
                af = step
            else:
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(max_step, af + step)
        else:
            if highs[i] > sar:
                uptrend = True
                sar = ep
                ep = highs[i]
                af = step
            else:
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(max_step, af + step)
    close = closes[-1]
    return 1.0 if (uptrend and close > sar) else 0.0


def keltner_breakout_target(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    period: int = 20,
    atr_mult: float = 1.5,
) -> float | None:
    """Keltner 通道突破 (TV 社区常用，类似 TTMSqueeze 外轨)."""
    if len(closes) < period + 2:
        return None
    mid = ema_last(closes, period)
    if mid is None:
        return None
    tr = _true_range(highs, lows, closes)
    atr_vals = _rma(tr, period)
    if not atr_vals:
        return None
    upper = mid + atr_mult * atr_vals[-1]
    lower = mid - atr_mult * atr_vals[-1]
    price = closes[-1]
    if price > upper:
        return 1.0
    if price < lower:
        return 0.0
    return None


def bb_squeeze_breakout_target(
    closes: list[float],
    *,
    bb_period: int = 20,
    bb_std: float = 2.0,
    squeeze_lookback: int = 120,
    bw_percentile: float = 20.0,
) -> float | None:
    """BB Squeeze (TV 热门): 带宽处于低位后向上突破上轨做多."""
    need = max(bb_period, squeeze_lookback) + 5
    if len(closes) < need:
        return None
    widths: list[float] = []
    for i in range(bb_period - 1, len(closes)):
        w = closes[i - bb_period + 1 : i + 1]
        mean = sum(w) / bb_period
        var = sum((x - mean) ** 2 for x in w) / bb_period
        std = math.sqrt(var) if var > 0 else 0.0
        upper = mean + bb_std * std
        lower = mean - bb_std * std
        widths.append((upper - lower) / mean if mean > 1e-12 else 0.0)
    if len(widths) < squeeze_lookback:
        return None
    recent = widths[-squeeze_lookback:]
    threshold = sorted(recent)[int(len(recent) * bw_percentile / 100.0)]
    squeezed = widths[-2] <= threshold
    w = closes[-bb_period:]
    mean = sum(w) / bb_period
    var = sum((x - mean) ** 2 for x in w) / bb_period
    std = math.sqrt(var) if var > 0 else 0.0
    upper = mean + bb_std * std
    if squeezed and closes[-1] > upper:
        return 1.0
    if closes[-1] < mean:
        return 0.0
    return None


def ichimoku_cloud_target(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    tenkan: int = 9,
    kijun: int = 26,
) -> float | None:
    """简化一目均衡表 (TV 内置): 价格在云上且转换>基准线."""
    if len(closes) < kijun + 2:
        return None
    th = highs[-tenkan:]
    tl = lows[-tenkan:]
    kh = highs[-kijun:]
    kl = lows[-kijun:]
    tenkan_line = (max(th) + min(tl)) / 2.0
    kijun_line = (max(kh) + min(kl)) / 2.0
    cloud_top = max(tenkan_line, kijun_line)
    cloud_bottom = min(tenkan_line, kijun_line)
    price = closes[-1]
    if price > cloud_top and tenkan_line > kijun_line:
        return 1.0
    if price < cloud_bottom:
        return 0.0
    return None


def vwap_trend_target(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    *,
    lookback: int = 20,
) -> float | None:
    """滚动 VWAP 趋势 (TV 日内/短线常用): 收盘价在 VWAP 上方持多."""
    if len(closes) < lookback or len(volumes) < lookback:
        return None
    num = 0.0
    den = 0.0
    for i in range(-lookback, 0):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        vol = max(0.0, volumes[i])
        num += tp * vol
        den += vol
    if den <= 1e-12:
        return None
    vwap = num / den
    return 1.0 if closes[-1] > vwap else 0.0


from quant_rd_tool.crypto_zipline_strategies import signals_tv_extended as tv_ext

SignalFn = Callable[..., float | None]

SIGNAL_BY_STRATEGY: dict[str, str] = {
    "ma_crossover": "ma_crossover",
    "ema_trend": "ema_trend",
    "momentum_rsi": "momentum_rsi",
    "bollinger_revert": "bollinger_revert",
    "donchian_breakout": "donchian_breakout",
    "macd_cross": "macd_cross",
    "volume_breakout": "volume_breakout",
    "supertrend": "supertrend",
    "supertrend_sized": "supertrend_sized",
    "stoch_rsi": "stoch_rsi",
    "golden_cross": "golden_cross",
    "ema_rsi_filter": "ema_rsi_filter",
    "macd_rsi_confirm": "macd_rsi_confirm",
    "adx_trend": "adx_trend",
    "psar_trend": "psar_trend",
    "keltner_breakout": "keltner_breakout",
    "bb_squeeze": "bb_squeeze",
    "ichimoku_cloud": "ichimoku_cloud",
    "vwap_trend": "vwap_trend",
    "hull_ma_trend": "hull_ma_trend",
    "dema_cross": "dema_cross",
    "t3_ma_trend": "t3_ma_trend",
    "alma_trend": "alma_trend",
    "zero_lag_ema": "zero_lag_ema",
    "ssl_channel": "ssl_channel",
    "chandelier_exit": "chandelier_exit",
    "aroon_trend": "aroon_trend",
    "linreg_channel": "linreg_channel",
    "williams_r": "williams_r",
    "cci_revert": "cci_revert",
    "tsi_momentum": "tsi_momentum",
    "ultimate_osc": "ultimate_osc",
    "wavetrend": "wavetrend",
    "fisher_transform": "fisher_transform",
    "connors_rsi": "connors_rsi",
    "rci_trend": "rci_trend",
    "coppock_curve": "coppock_curve",
    "kst_momentum": "kst_momentum",
    "squeeze_momentum": "squeeze_momentum",
    "keltner_squeeze": "keltner_squeeze",
    "atr_breakout": "atr_breakout",
    "mfi_revert": "mfi_revert",
    "obv_trend": "obv_trend",
    "chaikin_mf": "chaikin_mf",
    "vwap_cross": "vwap_cross",
    "heikin_ashi_trend": "heikin_ashi_trend",
    "elder_impulse": "elder_impulse",
    "tdi_dynamic": "tdi_dynamic",
    "ut_bot": "ut_bot",
    "range_filter": "range_filter",
}


def signal_for_strategy(
    strategy_id: str,
    closes: list[float],
    volumes: list[float],
    params: dict[str, Any],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    last_target: float = 0.0,
) -> float | None:
    hi = highs if highs is not None else closes
    lo = lows if lows is not None else closes
    if strategy_id == "ma_crossover":
        return ma_crossover_target(closes, fast=int(params["fast"]), slow=int(params["slow"]))
    if strategy_id == "ema_trend":
        return ema_crossover_target(closes, fast=int(params["fast"]), slow=int(params["slow"]))
    if strategy_id == "momentum_rsi":
        return rsi_target(
            closes,
            period=int(params["period"]),
            oversold=float(params["oversold"]),
            overbought=float(params["overbought"]),
            last_target=last_target,
        )
    if strategy_id == "bollinger_revert":
        return bollinger_target(
            closes,
            period=int(params["period"]),
            std_mult=float(params["std_mult"]),
            last_target=last_target,
        )
    if strategy_id == "donchian_breakout":
        return donchian_breakout_target(closes, channel=int(params["channel"]))
    if strategy_id == "macd_cross":
        return macd_cross_target(
            closes,
            fast=int(params["fast"]),
            slow=int(params["slow"]),
            signal=int(params["signal"]),
        )
    if strategy_id == "volume_breakout":
        return volume_breakout_target(
            closes,
            volumes,
            lookback=int(params["lookback"]),
            vol_mult=float(params["vol_mult"]),
        )
    if strategy_id == "supertrend":
        return supertrend_target(
            closes,
            hi,
            lo,
            atr_len=int(params.get("atr_len", 10)),
            factor=float(params.get("factor", 3.0)),
            last_target=last_target,
        )
    if strategy_id == "supertrend_sized":
        return supertrend_sized_target(
            closes,
            hi,
            lo,
            atr_len=int(params.get("atr_len", 10)),
            factor=float(params.get("factor", 3.0)),
            max_position=float(params.get("max_position", 0.5)),
            min_position=float(params.get("min_position", 0.15)),
            dist_atr=float(params.get("dist_atr", 2.0)),
            last_target=last_target,
        )
    if strategy_id == "stoch_rsi":
        return stoch_rsi_target(
            closes,
            rsi_period=int(params.get("rsi_period", 14)),
            stoch_period=int(params.get("stoch_period", 14)),
            k_smooth=int(params.get("k_smooth", 3)),
            d_smooth=int(params.get("d_smooth", 3)),
            oversold=float(params.get("oversold", 20)),
            overbought=float(params.get("overbought", 80)),
            last_target=last_target,
        )
    if strategy_id == "golden_cross":
        return golden_cross_target(
            closes,
            fast=int(params.get("fast", 50)),
            slow=int(params.get("slow", 200)),
        )
    if strategy_id == "ema_rsi_filter":
        return ema_rsi_filter_target(
            closes,
            fast=int(params["fast"]),
            slow=int(params["slow"]),
            rsi_period=int(params.get("rsi_period", 14)),
            rsi_min=float(params.get("rsi_min", 45)),
            rsi_max=float(params.get("rsi_max", 75)),
        )
    if strategy_id == "macd_rsi_confirm":
        return macd_rsi_confirm_target(
            closes,
            fast=int(params.get("fast", 12)),
            slow=int(params.get("slow", 26)),
            signal=int(params.get("signal", 9)),
            rsi_period=int(params.get("rsi_period", 14)),
            rsi_floor=float(params.get("rsi_floor", 50)),
            rsi_cap=float(params.get("rsi_cap", 70)),
        )
    if strategy_id == "adx_trend":
        return adx_trend_target(
            hi,
            lo,
            closes,
            period=int(params.get("period", 14)),
            adx_threshold=float(params.get("adx_threshold", 25)),
        )
    if strategy_id == "psar_trend":
        return psar_trend_target(
            hi,
            lo,
            closes,
            step=float(params.get("step", 0.02)),
            max_step=float(params.get("max_step", 0.2)),
        )
    if strategy_id == "keltner_breakout":
        return keltner_breakout_target(
            closes,
            hi,
            lo,
            period=int(params.get("period", 20)),
            atr_mult=float(params.get("atr_mult", 1.5)),
        )
    if strategy_id == "bb_squeeze":
        return bb_squeeze_breakout_target(
            closes,
            bb_period=int(params.get("bb_period", 20)),
            bb_std=float(params.get("bb_std", 2.0)),
            squeeze_lookback=int(params.get("squeeze_lookback", 120)),
            bw_percentile=float(params.get("bw_percentile", 20)),
        )
    if strategy_id == "ichimoku_cloud":
        return ichimoku_cloud_target(
            hi,
            lo,
            closes,
            tenkan=int(params.get("tenkan", 9)),
            kijun=int(params.get("kijun", 26)),
        )
    if strategy_id == "vwap_trend":
        return vwap_trend_target(
            closes,
            hi,
            lo,
            volumes,
            lookback=int(params.get("lookback", 20)),
        )
    p = params
    if strategy_id == "hull_ma_trend":
        return tv_ext.hull_ma_trend_target(closes, period=int(p.get("period", 55)))
    if strategy_id == "dema_cross":
        return tv_ext.dema_cross_target(closes, fast=int(p.get("fast", 12)), slow=int(p.get("slow", 26)))
    if strategy_id == "t3_ma_trend":
        return tv_ext.t3_ma_trend_target(closes, period=int(p.get("period", 8)), vfactor=float(p.get("vfactor", 0.7)))
    if strategy_id == "alma_trend":
        return tv_ext.alma_trend_target(closes, period=int(p.get("period", 9)), offset=float(p.get("offset", 0.85)), sigma=float(p.get("sigma", 6.0)))
    if strategy_id == "zero_lag_ema":
        return tv_ext.zero_lag_ema_target(closes, period=int(p.get("period", 21)))
    if strategy_id == "ssl_channel":
        return tv_ext.ssl_channel_target(hi, lo, closes, period=int(p.get("period", 10)))
    if strategy_id == "chandelier_exit":
        return tv_ext.chandelier_exit_target(hi, lo, closes, period=int(p.get("period", 22)), mult=float(p.get("mult", 3.0)))
    if strategy_id == "aroon_trend":
        return tv_ext.aroon_trend_target(hi, lo, period=int(p.get("period", 25)))
    if strategy_id == "linreg_channel":
        return tv_ext.linreg_channel_target(closes, period=int(p.get("period", 20)), mult=float(p.get("mult", 2.0)))
    if strategy_id == "williams_r":
        return tv_ext.williams_r_target(hi, lo, closes, period=int(p.get("period", 14)), oversold=float(p.get("oversold", -80)), overbought=float(p.get("overbought", -20)), last_target=last_target)
    if strategy_id == "cci_revert":
        return tv_ext.cci_revert_target(hi, lo, closes, period=int(p.get("period", 20)), oversold=float(p.get("oversold", -100)), overbought=float(p.get("overbought", 100)), last_target=last_target)
    if strategy_id == "tsi_momentum":
        return tv_ext.tsi_momentum_target(closes, long=int(p.get("long", 25)), short=int(p.get("short", 13)), signal=int(p.get("signal", 7)))
    if strategy_id == "ultimate_osc":
        return tv_ext.ultimate_osc_target(hi, lo, closes, period=int(p.get("period", 28)))
    if strategy_id == "wavetrend":
        return tv_ext.wavetrend_target(hi, lo, closes, channel_len=int(p.get("channel_len", 10)), avg_len=int(p.get("avg_len", 21)), ob_level=float(p.get("ob_level", 60)), os_level=float(p.get("os_level", -60)), last_target=last_target)
    if strategy_id == "fisher_transform":
        return tv_ext.fisher_transform_target(closes, period=int(p.get("period", 10)))
    if strategy_id == "connors_rsi":
        return tv_ext.connors_rsi_target(closes, rsi_period=int(p.get("rsi_period", 3)), streak_rsi=int(p.get("streak_rsi", 2)), pct_rank=int(p.get("pct_rank", 100)))
    if strategy_id == "rci_trend":
        return tv_ext.rci_trend_target(closes, period=int(p.get("period", 9)), threshold=float(p.get("threshold", 0)))
    if strategy_id == "coppock_curve":
        return tv_ext.coppock_curve_target(closes, wma_period=int(p.get("wma_period", 10)), roc1=int(p.get("roc1", 14)), roc2=int(p.get("roc2", 11)))
    if strategy_id == "kst_momentum":
        return tv_ext.kst_momentum_target(closes, signal=int(p.get("signal", 9)))
    if strategy_id == "squeeze_momentum":
        return tv_ext.squeeze_momentum_target(closes, hi, lo, bb_period=int(p.get("bb_period", 20)), bb_mult=float(p.get("bb_mult", 2.0)), kc_mult=float(p.get("kc_mult", 1.5)))
    if strategy_id == "keltner_squeeze":
        return tv_ext.keltner_squeeze_target(closes, hi, lo, period=int(p.get("period", 20)))
    if strategy_id == "atr_breakout":
        return tv_ext.atr_breakout_target(closes, hi, lo, period=int(p.get("period", 14)), mult=float(p.get("mult", 2.0)))
    if strategy_id == "mfi_revert":
        return tv_ext.mfi_revert_target(hi, lo, closes, volumes, period=int(p.get("period", 14)), oversold=float(p.get("oversold", 20)), overbought=float(p.get("overbought", 80)), last_target=last_target)
    if strategy_id == "obv_trend":
        return tv_ext.obv_trend_target(closes, volumes, period=int(p.get("period", 20)))
    if strategy_id == "chaikin_mf":
        return tv_ext.chaikin_mf_target(hi, lo, closes, volumes, period=int(p.get("period", 20)))
    if strategy_id == "vwap_cross":
        return tv_ext.vwap_cross_target(closes, hi, lo, volumes, lookback=int(p.get("lookback", 20)))
    if strategy_id == "heikin_ashi_trend":
        op = opens if opens is not None else [closes[max(0, i - 1)] for i in range(len(closes))]
        return tv_ext.heikin_ashi_trend_target(op, hi, lo, closes, min_bull=int(p.get("min_bull", 3)))
    if strategy_id == "elder_impulse":
        return tv_ext.elder_impulse_target(closes, hi, lo, ema_period=int(p.get("ema_period", 13)))
    if strategy_id == "tdi_dynamic":
        return tv_ext.tdi_dynamic_target(closes, rsi_period=int(p.get("rsi_period", 13)), band=int(p.get("band", 34)))
    if strategy_id == "ut_bot":
        return tv_ext.ut_bot_target(closes, hi, lo, key=float(p.get("key", 2.0)), atr_period=int(p.get("atr_period", 10)))
    if strategy_id == "range_filter":
        return tv_ext.range_filter_target(closes, period=int(p.get("period", 100)), mult=float(p.get("mult", 3.0)))
    return None
