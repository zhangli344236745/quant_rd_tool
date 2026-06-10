"""31 additional TradingView-style signal functions."""

from __future__ import annotations

import math

from quant_rd_tool.crypto_zipline_strategies import indicators as ind


def hull_ma_trend_target(closes: list[float], *, period: int = 55) -> float | None:
    h = ind.hull_ma(closes, period)
    if h is None:
        return None
    return 1.0 if closes[-1] > h else 0.0


def dema_cross_target(closes: list[float], *, fast: int = 12, slow: int = 26) -> float | None:
    if len(closes) < slow * 2:
        return None
    f = ind.dema_last(closes, fast)
    s = ind.dema_last(closes, slow)
    if f is None or s is None:
        return None
    return 1.0 if f > s else 0.0


def t3_ma_trend_target(closes: list[float], *, period: int = 8, vfactor: float = 0.7) -> float | None:
    if len(closes) < period * 6:
        return None
    e1 = ind.ema_series(closes, period)
    e2 = ind.ema_series(e1, period)
    e3 = ind.ema_series(e2, period)
    c1 = -vfactor ** 3
    c2 = 3 * vfactor ** 2 + 3 * vfactor ** 3
    c3 = -6 * vfactor ** 2 - 3 * vfactor - 3 * vfactor ** 3
    c4 = 1 + 3 * vfactor + vfactor ** 3 + 3 * vfactor ** 2
    t3 = c1 * e3[-1] + c2 * e2[-1] + c3 * e1[-1] + c4 * closes[-1]
    return 1.0 if closes[-1] > t3 else 0.0


def alma_trend_target(closes: list[float], *, period: int = 9, offset: float = 0.85, sigma: float = 6.0) -> float | None:
    if len(closes) < period:
        return None
    seg = closes[-period:]
    m = offset * (period - 1)
    s = period / sigma
    weights = [math.exp(-((i - m) ** 2) / (2 * s * s)) for i in range(period)]
    wsum = sum(weights)
    alma = sum(v * w for v, w in zip(seg, weights, strict=False)) / wsum
    return 1.0 if closes[-1] > alma else 0.0


def zero_lag_ema_target(closes: list[float], *, period: int = 21) -> float | None:
    z = ind.zlema_last(closes, period)
    if z is None:
        return None
    return 1.0 if closes[-1] > z else 0.0


def ssl_channel_target(
    highs: list[float], lows: list[float], closes: list[float], *, period: int = 10
) -> float | None:
    if len(closes) < period + 2:
        return None
    hi_sma = ind.sma(highs, period)
    lo_sma = ind.sma(lows, period)
    if hi_sma is None or lo_sma is None:
        return None
    hlv = 1 if closes[-1] > closes[-2] else (-1 if closes[-1] < closes[-2] else 0)
    ssl_down = hi_sma if hlv >= 0 else lo_sma
    return 1.0 if closes[-1] > ssl_down else 0.0


def chandelier_exit_target(
    highs: list[float], lows: list[float], closes: list[float], *, period: int = 22, mult: float = 3.0
) -> float | None:
    if len(closes) < period + 2:
        return None
    hh = max(highs[-period:])
    tr = ind.true_range(highs, lows, closes)
    atr = ind.rma(tr, period)
    if not atr:
        return None
    long_stop = hh - mult * atr[-1]
    return 1.0 if closes[-1] > long_stop else 0.0


def aroon_trend_target(highs: list[float], lows: list[float], *, period: int = 25) -> float | None:
    if len(highs) < period + 1:
        return None
    seg_h = highs[-period:]
    seg_l = lows[-period:]
    days_since_high = period - 1 - seg_h.index(max(seg_h))
    days_since_low = period - 1 - seg_l.index(min(seg_l))
    aroon_up = 100.0 * (period - days_since_high) / period
    aroon_down = 100.0 * (period - days_since_low) / period
    return 1.0 if aroon_up > aroon_down and aroon_up > 50 else 0.0


def linreg_channel_target(closes: list[float], *, period: int = 20, mult: float = 2.0) -> float | None:
    if len(closes) < period:
        return None
    seg = closes[-period:]
    n = len(seg)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(seg) / n
    slope = ind.linreg_slope(closes, period)
    if slope is None:
        return None
    intercept = y_mean - slope * x_mean
    reg = intercept + slope * (n - 1)
    resid = [seg[i] - (intercept + slope * i) for i in range(n)]
    std = math.sqrt(sum(r * r for r in resid) / n) if n else 0.0
    upper = reg + mult * std
    lower = reg - mult * std
    if closes[-1] > upper:
        return 1.0
    if closes[-1] < lower:
        return 0.0
    return 0.0


def williams_r_target(
    highs: list[float], lows: list[float], closes: list[float], *, period: int = 14,
    oversold: float = -80.0, overbought: float = -20.0, last_target: float = 0.0,
) -> float | None:
    if len(closes) < period:
        return None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll:
        return last_target
    wr = -100.0 * (hh - closes[-1]) / (hh - ll)
    if wr < oversold:
        return 1.0
    if wr > overbought:
        return 0.0
    return last_target


def cci_revert_target(
    highs: list[float], lows: list[float], closes: list[float], *, period: int = 20,
    oversold: float = -100.0, overbought: float = 100.0, last_target: float = 0.0,
) -> float | None:
    if len(closes) < period:
        return None
    tps = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(-period, 0)]
    mean = sum(tps) / period
    md = sum(abs(tp - mean) for tp in tps) / period
    if md == 0:
        return last_target
    cci = (tps[-1] - mean) / (0.015 * md)
    if cci < oversold:
        return 1.0
    if cci > overbought:
        return 0.0
    return last_target


def tsi_momentum_target(closes: list[float], *, long: int = 25, short: int = 13, signal: int = 7) -> float | None:
    if len(closes) < long + short + signal + 2:
        return None
    pc = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    abs_pc = [abs(x) for x in pc]
    double_smooth = lambda vals, p: ind.ema_series(ind.ema_series(vals, p), p)
    sm_pc = double_smooth(pc, long)
    sm_abs = double_smooth(abs_pc, long)
    if not sm_pc or not sm_abs or sm_abs[-1] == 0:
        return None
    tsi = 100.0 * sm_pc[-1] / sm_abs[-1]
    tsi_series = [100.0 * sm_pc[i] / sm_abs[i] if sm_abs[i] else 0.0 for i in range(len(sm_pc))]
    sig = ind.ema_series(tsi_series, signal)
    if not sig:
        return None
    return 1.0 if tsi > sig[-1] else 0.0


def ultimate_osc_target(
    highs: list[float], lows: list[float], closes: list[float], *, period: int = 28,
) -> float | None:
    if len(closes) < period + 2:
        return None
    bp = [closes[i] - min(lows[i], closes[i - 1]) for i in range(1, len(closes))]
    tr = ind.true_range(highs, lows, closes)[1:]
    if len(bp) < period:
        return None
    avg7 = sum(bp[-7:]) / sum(tr[-7:]) if sum(tr[-7:]) else 0.0
    avg14 = sum(bp[-14:]) / sum(tr[-14:]) if sum(tr[-14:]) else 0.0
    avg28 = sum(bp[-period:]) / sum(tr[-period:]) if sum(tr[-period:]) else 0.0
    uo = 100.0 * (4 * avg7 + 2 * avg14 + avg28) / 7.0
    return 1.0 if uo > 50 else 0.0


def wavetrend_target(
    highs: list[float], lows: list[float], closes: list[float], *,
    channel_len: int = 10, avg_len: int = 21, ob_level: float = 60.0, os_level: float = -60.0,
    last_target: float = 0.0,
) -> float | None:
    if len(closes) < channel_len + avg_len + 4:
        return None
    hlc3 = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    esa = ind.ema_series(hlc3, channel_len)
    d = ind.ema_series([abs(hlc3[i] - esa[i]) for i in range(len(hlc3))], channel_len)
    ci = [(hlc3[i] - esa[i]) / (0.015 * d[i]) if d[i] else 0.0 for i in range(len(hlc3))]
    wt1 = ind.ema_series(ci, avg_len)
    wt2 = ind.ema_series(wt1, 4)
    if len(wt1) < 2 or len(wt2) < 2:
        return None
    if wt1[-1] > wt2[-1] and wt1[-2] <= wt2[-2] and wt1[-1] < os_level:
        return 1.0
    if wt1[-1] < wt2[-1] and wt1[-1] > ob_level:
        return 0.0
    return last_target


def fisher_transform_target(closes: list[float], *, period: int = 10) -> float | None:
    if len(closes) < period + 5:
        return None
    highs = closes
    lows = closes
    val = 0.0
    fish = 0.0
    prev_fish = 0.0
    for i in range(period - 1, len(closes)):
        seg_h = highs[i - period + 1 : i + 1]
        seg_l = lows[i - period + 1 : i + 1]
        hi, lo = max(seg_h), min(seg_l)
        x = 0.66 * ((closes[i] - lo) / (hi - lo) - 0.5) + 0.67 * val if hi != lo else val
        x = max(-0.999, min(0.999, x))
        val = x
        fish = 0.5 * math.log((1 + x) / (1 - x)) + 0.5 * prev_fish
        prev_fish = fish
    return 1.0 if fish > prev_fish else 0.0


def connors_rsi_target(closes: list[float], *, rsi_period: int = 3, streak_rsi: int = 2, pct_rank: int = 100) -> float | None:
    if len(closes) < pct_rank + 5:
        return None
    rsi = ind.rsi_value(closes, rsi_period)
    if rsi is None:
        return None
    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            streak = streak + 1 if streak >= 0 else 1
        elif closes[i] < closes[i - 1]:
            streak = streak - 1 if streak <= 0 else -1
        else:
            break
    streak_vals = []
    s = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            s = s + 1 if s >= 0 else 1
        elif closes[i] < closes[i - 1]:
            s = s - 1 if s <= 0 else -1
        else:
            s = 0
        streak_vals.append(float(s))
    if len(streak_vals) < streak_rsi:
        return None
    streak_rsi_val = ind.rsi_value(streak_vals, streak_rsi) or 50.0
    rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes))]
    rank = sum(1 for r in rets[-pct_rank:] if r <= rets[-1]) / min(pct_rank, len(rets)) * 100.0
    crsi = (rsi + streak_rsi_val + rank) / 3.0
    if crsi < 20:
        return 1.0
    if crsi > 80:
        return 0.0
    return None


def rci_trend_target(closes: list[float], *, period: int = 9, threshold: float = 0.0) -> float | None:
    if len(closes) < period:
        return None
    seg = closes[-period:]
    date_rank = list(range(1, period + 1))
    price_rank = sorted(range(1, period + 1), key=lambda i: seg[i - 1])
    d = sum((date_rank[i] - price_rank[i]) ** 2 for i in range(period))
    rci = (1 - 6 * d / (period * (period ** 2 - 1))) * 100
    return 1.0 if rci > threshold else 0.0


def coppock_curve_target(closes: list[float], *, wma_period: int = 10, roc1: int = 14, roc2: int = 11) -> float | None:
    need = max(roc1, roc2) + wma_period + 2
    if len(closes) < need:
        return None
    def roc(n: int) -> float:
        return (closes[-1] / closes[-1 - n] - 1.0) * 100.0
    val = roc(roc1) + roc(roc2)
    series = []
    for i in range(need, len(closes) + 1):
        sub = closes[:i]
        r1 = (sub[-1] / sub[-1 - roc1] - 1.0) * 100.0
        r2 = (sub[-1] / sub[-1 - roc2] - 1.0) * 100.0
        series.append(r1 + r2)
    w = ind.wma(series, wma_period)
    if w is None:
        return None
    return 1.0 if w > 0 else 0.0


def kst_momentum_target(closes: list[float], *, signal: int = 9) -> float | None:
    if len(closes) < 60:
        return None
    def roc_sma(n: int, m: int) -> float:
        rocs = [(closes[i] / closes[i - n] - 1.0) * 100.0 for i in range(n, len(closes))]
        return sum(rocs[-m:]) / m if len(rocs) >= m else 0.0
    kst = (
        roc_sma(10, 10) * 1
        + roc_sma(15, 10) * 2
        + roc_sma(20, 10) * 3
        + roc_sma(30, 15) * 4
    )
    kst_series = []
    for i in range(60, len(closes) + 1):
        sub = closes[:i]
        def rs(n: int, m: int) -> float:
            rocs = [(sub[j] / sub[j - n] - 1.0) * 100.0 for j in range(n, len(sub))]
            return sum(rocs[-m:]) / m if len(rocs) >= m else 0.0
        kst_series.append(rs(10, 10) + 2 * rs(15, 10) + 3 * rs(20, 10) + 4 * rs(30, 15))
    sig = ind.ema_series(kst_series, signal)
    if not sig:
        return None
    return 1.0 if kst > sig[-1] else 0.0


def squeeze_momentum_target(
    closes: list[float], highs: list[float], lows: list[float], *, bb_period: int = 20,
    bb_mult: float = 2.0, kc_mult: float = 1.5,
) -> float | None:
    if len(closes) < bb_period + 5:
        return None
    w = closes[-bb_period:]
    mean = sum(w) / bb_period
    std = math.sqrt(sum((x - mean) ** 2 for x in w) / bb_period)
    tr = ind.true_range(highs, lows, closes)
    atr = ind.rma(tr, bb_period)
    if not atr:
        return None
    kc_mid = ind.ema_last(closes, bb_period) or mean
    squeezed = (mean + bb_mult * std) < (kc_mid + kc_mult * atr[-1]) and (
        mean - bb_mult * std
    ) > (kc_mid - kc_mult * atr[-1])
    momentum = closes[-1] - mean
    if squeezed and momentum > 0:
        return 1.0
    if momentum < 0:
        return 0.0
    return None


def keltner_squeeze_target(
    closes: list[float], highs: list[float], lows: list[float], *, period: int = 20,
) -> float | None:
    if len(closes) < period + 5:
        return None
    w = closes[-period:]
    mean = sum(w) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in w) / period)
    tr = ind.true_range(highs, lows, closes)
    atr = ind.rma(tr, period)
    if not atr:
        return None
    kc_mid = ind.ema_last(closes, period) or mean
    inside = (mean + 2 * std) < (kc_mid + 1.5 * atr[-1]) and (mean - 2 * std) > (kc_mid - 1.5 * atr[-1])
    if inside and closes[-1] > mean:
        return 1.0
    if closes[-1] < kc_mid - 1.5 * atr[-1]:
        return 0.0
    return None


def atr_breakout_target(
    closes: list[float], highs: list[float], lows: list[float], *, period: int = 14, mult: float = 2.0,
) -> float | None:
    if len(closes) < period + 2:
        return None
    tr = ind.true_range(highs, lows, closes)
    atr = ind.rma(tr, period)
    if not atr:
        return None
    mid = ind.ema_last(closes, period)
    if mid is None:
        return None
    upper = mid + mult * atr[-1]
    lower = mid - mult * atr[-1]
    if closes[-1] > upper:
        return 1.0
    if closes[-1] < lower:
        return 0.0
    return 0.0


def mfi_revert_target(
    highs: list[float], lows: list[float], closes: list[float], volumes: list[float], *,
    period: int = 14, oversold: float = 20.0, overbought: float = 80.0, last_target: float = 0.0,
) -> float | None:
    if len(closes) < period + 1 or len(volumes) < period + 1:
        return None
    pos = neg = 0.0
    for i in range(-period, 0):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        prev = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3.0
        mf = tp * volumes[i]
        if tp > prev:
            pos += mf
        elif tp < prev:
            neg += mf
    if neg == 0:
        mfi = 100.0
    else:
        mfi = 100.0 - 100.0 / (1.0 + pos / neg)
    if mfi < oversold:
        return 1.0
    if mfi > overbought:
        return 0.0
    return last_target


def obv_trend_target(closes: list[float], volumes: list[float], *, period: int = 20) -> float | None:
    if len(closes) < period + 2:
        return None
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    obv_ma = ind.sma(obv, period)
    if obv_ma is None:
        return None
    return 1.0 if obv[-1] > obv_ma else 0.0


def chaikin_mf_target(
    highs: list[float], lows: list[float], closes: list[float], volumes: list[float], *, period: int = 20,
) -> float | None:
    if len(closes) < period:
        return None
    mf = []
    for i in range(-period, 0):
        hl = highs[i] - lows[i]
        mfm = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl if hl else 0.0
        mf.append(mfm * volumes[i])
    cmf = sum(mf) / sum(volumes[-period:]) if sum(volumes[-period:]) else 0.0
    return 1.0 if cmf > 0 else 0.0


def vwap_cross_target(
    closes: list[float], highs: list[float], lows: list[float], volumes: list[float], *, lookback: int = 20,
) -> float | None:
    if len(closes) < lookback + 2:
        return None
    num = den = 0.0
    for i in range(-lookback, 0):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        num += tp * volumes[i]
        den += volumes[i]
    if den <= 0:
        return None
    vwap = num / den
    prev_num = prev_den = 0.0
    for i in range(-lookback - 1, -1):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        prev_num += tp * volumes[i]
        prev_den += volumes[i]
    prev_vwap = prev_num / prev_den if prev_den else vwap
    if closes[-1] > vwap and closes[-2] <= prev_vwap:
        return 1.0
    if closes[-1] < vwap:
        return 0.0
    return None


def heikin_ashi_trend_target(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float], *, min_bull: int = 3,
) -> float | None:
    if len(closes) < min_bull + 2:
        return None
    ha_close = [(opens[i] + highs[i] + lows[i] + closes[i]) / 4.0 for i in range(len(closes))]
    ha_open = [ha_close[0]]
    for i in range(1, len(closes)):
        ha_open.append((ha_open[-1] + ha_close[i - 1]) / 2.0)
    bull = all(ha_close[i] > ha_open[i] for i in range(-min_bull, 0))
    return 1.0 if bull else (0.0 if ha_close[-1] < ha_open[-1] else None)


def elder_impulse_target(
    closes: list[float], highs: list[float], lows: list[float], *, ema_period: int = 13,
) -> float | None:
    if len(closes) < ema_period + 5:
        return None
    ema = ind.ema_last(closes, ema_period)
    macd, _ = ind.macd_lines(closes, fast=12, slow=26, signal=9)
    if ema is None or macd is None:
        return None
    hist_rising = len(closes) >= 3 and closes[-1] > closes[-2]
    if closes[-1] > ema and macd > 0 and hist_rising:
        return 1.0
    if closes[-1] < ema and macd < 0:
        return 0.0
    return None


def tdi_dynamic_target(closes: list[float], *, rsi_period: int = 13, band: int = 34) -> float | None:
    if len(closes) < band + rsi_period:
        return None
    rsi = ind.rsi_value(closes, rsi_period)
    if rsi is None:
        return None
    rsi_series = []
    for i in range(rsi_period + 1, len(closes) + 1):
        v = ind.rsi_value(closes[:i], rsi_period)
        if v is not None:
            rsi_series.append(v)
    if len(rsi_series) < band:
        return None
    mid = sum(rsi_series[-band:]) / band
    return 1.0 if rsi > mid and rsi > 50 else 0.0


def ut_bot_target(
    closes: list[float], highs: list[float], lows: list[float], *, key: float = 2.0, atr_period: int = 10,
) -> float | None:
    if len(closes) < atr_period + 3:
        return None
    tr = ind.true_range(highs, lows, closes)
    atr = ind.rma(tr, atr_period)
    if not atr:
        return None
    n_loss = key * atr[-1]
    trailing = closes[-1] - n_loss
    return 1.0 if closes[-1] > trailing else 0.0


def range_filter_target(closes: list[float], *, period: int = 100, mult: float = 3.0) -> float | None:
    if len(closes) < period + 2:
        return None
    w = closes[-period:]
    av = sum(abs(w[i] - w[i - 1]) for i in range(1, len(w))) / (len(w) - 1)
    rng = av * mult
    filt = closes[-2]
    if closes[-1] - filt > rng:
        filt = closes[-1] - rng
    elif filt - closes[-1] > rng:
        filt = closes[-1] + rng
    return 1.0 if closes[-1] > filt else 0.0
