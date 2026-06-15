"""Tests for scheduled A-share announcement scans."""

from __future__ import annotations

from unittest.mock import patch


def test_run_announcement_cycle_evaluates_alerts():
    digest = {
        "generated_at": "2026-06-12T12:00:00+00:00",
        "top_items": [{"code": "600519", "title": "业绩预增", "score": 80, "keywords": ["业绩预增"]}],
    }
    expected = {"items_processed": 1, "items_new": 1, "digest": digest}
    with patch("quant_rd_tool.stock_announcement_scheduler.run_announcement_scan", return_value=expected):
        with patch("quant_rd_tool.schedule_alerts.evaluate_announcement_alerts") as mock_alert:
            from quant_rd_tool.stock_announcement_scheduler import run_announcement_cycle

            out = run_announcement_cycle(job_id="ann-job", data_dir="data/stocks")
    assert out["items_new"] == 1
    mock_alert.assert_called_once_with("ann-job", digest)


def test_stock_announcements_job_run_once(tmp_path):
    from quant_rd_tool.scheduler_manager import ScheduleJobConfig, SchedulerManager

    registry = tmp_path / "schedules.json"
    mgr = SchedulerManager(registry)
    mgr.add_job(
        ScheduleJobConfig(
            symbols=[],
            data_dir=str(tmp_path / "data" / "stocks"),
            job_type="stock_announcements",
            interval_minutes=360,
            use_watchlist=True,
        )
    )
    fake = {
        "items_processed": 2,
        "items_new": 1,
        "digest": {"top_items": [{"score": 75}], "symbols_scanned": 2},
        "fetch_errors": [],
    }
    with patch("quant_rd_tool.stock_announcement_scheduler.run_announcement_cycle", return_value=fake):
        out = mgr.run_once(mgr.list_jobs()[0]["id"], precheck_connectivity=False)
    assert out["job"]["run_count"] == 1
    assert out["job"]["last_cycle_summary"][0]["job_type"] == "stock_announcements"
