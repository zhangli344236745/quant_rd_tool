"""Shared indicator helpers for TV strategy signals."""

from __future__ import annotations

import math


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


def ema_series(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def rsi_value(closes: list[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    window = closes[-(period + 1) :]
    gains = losses = 0.0
    for i in range(1, len(window)):
        delta = window[i] - window[i - 1]
        if delta > 0:
            gains += delta
        elif delta < 0:
            losses -= delta
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = (gains / period) / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(len(closes)):
        if i == 0:
            out.append(highs[i] - lows[i])
        else:
            out.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
    return out


def rma(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    alpha = 1.0 / period
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def macd_lines(
    closes: list[float], *, fast: int, slow: int, signal: int
) -> tuple[float | None, float | None]:
    if len(closes) < slow + signal:
        return None, None
    fast_line = ema_series(closes, fast)
    slow_line = ema_series(closes, slow)
    macd_line = [f - s for f, s in zip(fast_line, slow_line, strict=False)]
    sig_alpha = 2.0 / (signal + 1)
    sig = macd_line[0]
    for m in macd_line[1:]:
        sig = sig_alpha * m + (1 - sig_alpha) * sig
    return macd_line[-1], sig


def wma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    seg = values[-period:]
    weights = list(range(1, period + 1))
    return sum(v * w for v, w in zip(seg, weights, strict=False)) / sum(weights)


def hull_ma(values: list[float], period: int) -> float | None:
    half = max(1, period // 2)
    sqrt_p = max(1, int(math.sqrt(period)))
    if len(values) < period:
        return None
    raw: list[float] = []
    for i in range(period - 1, len(values)):
        seg = values[i - period + 1 : i + 1]
        wh = wma(seg, half)
        wl = wma(seg, period)
        if wh is None or wl is None:
            continue
        raw.append(2 * wh - wl)
    if len(raw) < sqrt_p:
        return None
    return wma(raw, sqrt_p)


def dema_last(values: list[float], span: int) -> float | None:
    if len(values) < span * 2:
        return None
    ema1 = ema_series(values, span)
    ema2 = ema_series(ema1, span)
    return 2 * ema1[-1] - ema2[-1]


def zlema_last(values: list[float], span: int) -> float | None:
    if len(values) < span:
        return None
    lag = max(1, (span - 1) // 2)
    if len(values) <= lag:
        return None
    adj = [2 * values[i] - values[i - lag] for i in range(lag, len(values))]
    return ema_last(adj, span)


def linreg_slope(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    seg = values[-period:]
    n = len(seg)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(seg) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, seg, strict=False))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den
