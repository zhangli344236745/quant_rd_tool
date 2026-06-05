"""A-share zipline lab timeframes (daily bars)."""

from __future__ import annotations

SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("1d",)
TIMEFRAME_BAR_MINUTES: dict[str, int] = {"1d": 1440}
DEFAULT_TIMEFRAME = "1d"


def normalize_timeframe(timeframe: str) -> str:
    tf = (timeframe or DEFAULT_TIMEFRAME).strip().lower()
    if tf in ("1d", "day", "daily"):
        return "1d"
    if tf not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"A-share lab supports daily only, got {timeframe!r}")
    return tf


def bar_minutes_for(timeframe: str) -> int:
    return TIMEFRAME_BAR_MINUTES[normalize_timeframe(timeframe)]


def bundle_name_for(timeframe: str) -> str:
    return f"stock_ashare_{normalize_timeframe(timeframe)}"


def list_timeframe_options() -> list[dict[str, str | int]]:
    return [{"id": "1d", "label": "日线", "bar_minutes": 1440}]
