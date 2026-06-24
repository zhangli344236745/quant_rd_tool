"""Project-wide timestamps in Asia/Shanghai (北京时间)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def now_beijing() -> datetime:
    return datetime.now(BEIJING_TZ)


def now_iso() -> str:
    """Current time as ISO 8601 with +08:00 offset."""
    return now_beijing().isoformat()


def to_beijing_iso(dt: datetime | None = None) -> str:
    if dt is None:
        return now_iso()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(BEIJING_TZ).isoformat()


def today_beijing_date() -> str:
    return now_beijing().date().isoformat()


def parse_iso(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))
