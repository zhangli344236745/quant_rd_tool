from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from quant_rd_tool.time_util import BEIJING_TZ, now_iso, to_beijing_iso, today_beijing_date


def test_now_iso_beijing_offset():
    iso = now_iso()
    assert "+08:00" in iso or iso.endswith("+08:00")


def test_to_beijing_iso_from_utc():
    utc = datetime(2026, 6, 24, 1, 25, 38, tzinfo=UTC)
    bj = to_beijing_iso(utc)
    assert "+08:00" in bj
    assert "09:25:38" in bj


def test_today_beijing_date_format():
    assert len(today_beijing_date()) == 10
    assert BEIJING_TZ.key == "Asia/Shanghai"
