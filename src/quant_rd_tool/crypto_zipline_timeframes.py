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


def list_timeframe_options() -> list[dict[str, str | int]]:
    return [
        {"id": tf, "label": tf, "bar_minutes": TIMEFRAME_BAR_MINUTES[tf]}
        for tf in SUPPORTED_TIMEFRAMES
    ]
