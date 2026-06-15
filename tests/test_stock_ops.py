"""Tests for A-share ops dashboard helpers and routes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_check_akshare_connectivity_local_cache(tmp_path: Path):
    from quant_rd_tool.stock_ops import check_akshare_connectivity

    fake_df = type("DF", (), {"__len__": lambda self: 5})()
    with patch("quant_rd_tool.stock_var.fetch_ohlcv_df", return_value=fake_df):
        out = check_akshare_connectivity(probe_code="600519", data_dir=str(tmp_path))
    assert out["ok"] is True
    assert out["source"] == "local_cache"
    assert out["bars"] == 5


def test_scan_data_freshness_marks_stale(tmp_path: Path):
    from quant_rd_tool.stock_ops import scan_data_freshness

    with (
        patch("quant_rd_tool.stock_ops.resolve_stock_symbols", return_value=["600519"]),
        patch(
            "quant_rd_tool.stock_ops.data_status",
            return_value={"symbol": "SH600519", "ready": True, "bars_count": 100, "last_bar": "2020-01-01"},
        ),
    ):
        out = scan_data_freshness(data_dir=str(tmp_path), symbols=["600519"], use_watchlist=False)
    assert out["symbols_checked"] == 1
    assert out["stale_count"] == 1
    assert out["items"][0]["stale"] is True


def test_build_stock_ops_summary(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.stock_ops import build_stock_ops_summary

    fake_jobs = [{"id": "ann-1d", "status": "stopped", "job_type": "stock_announcements"}]
    with (
        patch("quant_rd_tool.scheduler_manager.get_scheduler_manager") as mgr_cls,
        patch("quant_rd_tool.stock_ops.check_akshare_connectivity", return_value={"ok": True, "probe_code": "600519"}),
        patch(
            "quant_rd_tool.stock_ops.scan_data_freshness",
            return_value={"symbols_checked": 1, "stale_count": 0, "items": []},
        ),
        patch("quant_rd_tool.stock_announcement_radar.load_digest", return_value={"top_items": [], "items_new": 0}),
        patch("quant_rd_tool.schedule_alerts.evaluate_stale_jobs", return_value=[]),
        patch("quant_rd_tool.schedule_alerts.get_alert_rules", return_value={"enabled": True}),
        patch("quant_rd_tool.schedule_alerts.tail_alert_log", return_value=[]),
    ):
        mgr = mgr_cls.return_value
        mgr.list_jobs.return_value = fake_jobs
        out = build_stock_ops_summary(data_dir=str(tmp_path / "stocks"))
    assert out["market"] == "stock"
    assert out["schedules"]["total"] == 1
    assert out["connectivity"]["ok"] is True


def test_stock_ops_routes_smoke(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.main import app

    fake = {
        "market": "stock",
        "connectivity": {"ok": True},
        "data_freshness": {"stale_count": 0, "items": []},
        "announcements": {},
        "schedules": {"total": 0, "running": 0, "jobs": []},
    }
    with patch("quant_rd_tool.stock_ops.build_stock_ops_summary", return_value=fake):
        with TestClient(app) as client:
            r = client.get("/api/v1/stocks/ops/summary")
            assert r.status_code == 200, r.text
            assert r.json()["market"] == "stock"

            r2 = client.get("/api/v1/stocks/ops/connectivity")
            assert r2.status_code == 200, r2.text
