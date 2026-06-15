"""Scheduler manager integration for A-share jobs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from quant_rd_tool.scheduler_manager import ScheduleJobConfig, SchedulerManager, reset_scheduler_manager


def test_stock_job_run_once(tmp_path: Path):
    registry = tmp_path / "schedules.json"
    mgr = SchedulerManager(registry)
    mgr.add_job(
        ScheduleJobConfig(
            symbols=["600519"],
            data_dir=str(tmp_path / "data" / "stocks"),
            job_type="stock_qlib",
            interval_minutes=1440,
            years=2,
        )
    )
    fake = [
        {
            "code": "600519",
            "symbol": "SH600519",
            "narrative": {"stance": "中性"},
            "summary": {},
        }
    ]
    with patch("quant_rd_tool.scheduler_manager.run_stock_scheduled_cycle", return_value=fake):
        out = mgr.run_once("600519-1d", precheck_connectivity=False)
    assert out["job"]["run_count"] == 1
    assert out["job"]["last_cycle_summary"][0]["stance"] == "中性"


def test_separate_managers_per_data_dir(tmp_path: Path, monkeypatch):
    reset_scheduler_manager()
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    crypto_dir = str(tmp_path / "data" / "crypto")
    stock_dir = str(tmp_path / "data" / "stocks")
    get_scheduler_manager(crypto_dir).add_job(
        ScheduleJobConfig(symbols=["BTC"], timeframe="5m", data_dir=crypto_dir)
    )
    get_scheduler_manager(stock_dir).add_job(
        ScheduleJobConfig(
            symbols=["600519"],
            data_dir=stock_dir,
            job_type="stock_qlib",
        )
    )
    assert len(get_scheduler_manager(crypto_dir).list_jobs()) == 1
    assert len(get_scheduler_manager(stock_dir).list_jobs()) == 1
    reset_scheduler_manager()
