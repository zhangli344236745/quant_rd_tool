"""Enhanced crypto trading signal: multi-timeframe confirmation + volatility,
volume and trend filters layered on top of the base technical signal.

The base bot signal (``derive_trading_signal``) is a single-timeframe rule score.
That fires too often in chop and ignores the higher-timeframe regime. This module
gates and scales that signal so the bot only acts on higher-conviction setups.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_rd_tool.crypto_analyzer import analyze_crypto_ohlcv, derive_trading_signal

# Higher timeframe to confirm each base timeframe against.
HTF_MAP: dict[str, str] = {
    "1m": "15m",
    "3m": "30m",
    "5m": "1h",
    "15m": "4h",
    "30m": "4h",
    "1h": "1d",
    "2h": "1d",
    "4h": "1d",
    "1d": "1w",
}


def higher_timeframe_for(timeframe: str) -> str:
    return HTF_MAP.get((timeframe or "1d").strip().lower(), "1d")


def _trend_direction(analysis: dict[str, Any]) -> str:
    """Coarse regime label from MA alignment of an analysis block."""
    ma = (analysis.get("technical") or {}).get("ma_alignment")
    if ma == "多头排列":
        return "up"
    if ma == "空头排列":
        return "down"
    return "range"


def compute_atr_pct(df: pd.DataFrame, *, period: int = 14) -> float | None:
    """ATR as a fraction of latest close (volatility regime proxy)."""
    if df is None or len(df) < period + 1:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean().dropna()
    if atr.empty:
        return None
    last_close = float(close.iloc[-1])
    if last_close <= 0:
        return None
    return float(atr.iloc[-1] / last_close)


def volume_confirms(df: pd.DataFrame, *, lookback: int = 20, min_ratio: float = 1.0) -> bool | None:
    """True when latest volume >= min_ratio * average of prior ``lookback`` bars."""
    if df is None or "volume" not in df.columns or len(df) < lookback + 1:
        return None
    vol = df["volume"].astype(float)
    avg = float(vol.iloc[-(lookback + 1) : -1].mean())
    if avg <= 0:
        return None
    return bool(float(vol.iloc[-1]) >= min_ratio * avg)


def build_enhanced_signal(
    base_df: pd.DataFrame,
    htf_df: pd.DataFrame | None = None,
    *,
    timeframe: str = "1d",
    atr_period: int = 14,
    min_atr_pct: float = 0.0,
    max_atr_pct: float = 0.0,
    volume_lookback: int = 20,
    volume_min_ratio: float = 1.0,
    require_htf_confirm: bool = True,
    require_volume_confirm: bool = False,
) -> dict[str, Any]:
    """Layer multi-timeframe + volatility/volume/trend filters on the base signal.

    Returns the base signal enriched with ``filters``, ``gates`` and a possibly
    downgraded ``action`` (to ``hold``) plus a scaled ``confidence``.
    """
    base_analysis = analyze_crypto_ohlcv(base_df)
    base_signal = derive_trading_signal(base_analysis)
    action = base_signal["action"]
    confidence = float(base_signal.get("confidence") or 0.0)

    gates: list[str] = []
    passed = True

    # 1) Higher-timeframe trend confirmation.
    htf_trend = None
    if htf_df is not None and len(htf_df) >= 60:
        htf_trend = _trend_direction(analyze_crypto_ohlcv(htf_df))
    htf_confirms: bool | None = None
    if htf_trend is not None and action in ("buy", "sell"):
        if action == "buy":
            htf_confirms = htf_trend != "down"
        else:
            htf_confirms = htf_trend != "up"
        if require_htf_confirm and not htf_confirms:
            passed = False
            gates.append(f"高周期趋势({htf_trend})与{action}方向冲突")
        elif htf_confirms:
            confidence = min(1.0, confidence + 0.1)

    # 2) Volatility regime filter (ATR%).
    atr_pct = compute_atr_pct(base_df, period=atr_period)
    if atr_pct is not None and action in ("buy", "sell"):
        if min_atr_pct > 0 and atr_pct < min_atr_pct:
            passed = False
            gates.append(f"波动率过低 ATR%={atr_pct:.4f} < {min_atr_pct:.4f}")
        if max_atr_pct > 0 and atr_pct > max_atr_pct:
            passed = False
            gates.append(f"波动率过高 ATR%={atr_pct:.4f} > {max_atr_pct:.4f}")

    # 3) Volume confirmation.
    vol_ok = volume_confirms(base_df, lookback=volume_lookback, min_ratio=volume_min_ratio)
    if vol_ok is not None and action in ("buy", "sell"):
        if require_volume_confirm and not vol_ok:
            passed = False
            gates.append("成交量未放大确认")
        elif vol_ok:
            confidence = min(1.0, confidence + 0.05)

    final_action = action if passed else "hold"
    final_stance = base_signal["stance"] if passed else "中性"

    return {
        **base_signal,
        "action": final_action,
        "stance": final_stance,
        "base_action": action,
        "confidence": round(confidence if passed else 0.0, 4),
        "filters": {
            "htf_timeframe": higher_timeframe_for(timeframe),
            "htf_trend": htf_trend,
            "htf_confirms": htf_confirms,
            "atr_pct": round(atr_pct, 6) if atr_pct is not None else None,
            "volume_confirms": vol_ok,
        },
        "gates": gates,
        "gated": not passed,
    }
