"""Supported OHLCV timeframes for zipline strategy lab."""

from __future__ import annotations

SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "30m", "1h", "4h", "1d")

# Bar spacing in minutes (for zipline sparse-minute bundles)
TIMEFRAME_BAR_MINUTES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

DEFAULT_TIMEFRAME = "15m"

# Crypto trades 24/7: bars per 365-day year for annualization
BARS_PER_YEAR: dict[str, int] = {
    "5m": 105_120,
    "15m": 35_040,
    "30m": 17_520,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


def bars_per_year_for(timeframe: str) -> int:
    return BARS_PER_YEAR[normalize_timeframe(timeframe)]


def normalize_timeframe(timeframe: str) -> str:
    tf = (timeframe or DEFAULT_TIMEFRAME).strip().lower()
    if tf in ("1d", "day", "daily"):
        return "1d"
    if tf not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}; use one of {', '.join(SUPPORTED_TIMEFRAMES)}"
        )
    return tf


def bar_minutes_for(timeframe: str) -> int:
    return TIMEFRAME_BAR_MINUTES[normalize_timeframe(timeframe)]


def bundle_name_for(timeframe: str) -> str:
    return f"crypto_ccxt_{normalize_timeframe(timeframe)}"


ML_WINDOW_SCALE: dict[str, float] = {
    "5m": 1.0,
    "15m": 1.0,
    "30m": 0.75,
    "1h": 0.25,
    "4h": 0.1,
    "1d": 0.05,
}


def ml_window_scale(timeframe: str) -> float:
    return ML_WINDOW_SCALE[normalize_timeframe(timeframe)]


def effective_ml_train_bars(timeframe: str, base: int = 2000) -> int:
    return max(200, int(base * ml_window_scale(timeframe)))


def list_timeframe_options() -> list[dict[str, str | int]]:
    return [
        {"id": tf, "label": tf, "bar_minutes": TIMEFRAME_BAR_MINUTES[tf]}
        for tf in SUPPORTED_TIMEFRAMES
    ]
