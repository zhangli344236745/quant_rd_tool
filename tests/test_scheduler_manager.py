"""Tests for scheduler manager (no network)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from quant_rd_tool.scheduler_manager import ScheduleJobConfig, SchedulerManager, reset_scheduler_manager


def test_add_list_remove(tmp_path: Path):
    registry = tmp_path / "schedules.json"
    mgr = SchedulerManager(registry)
    job = mgr.add_job(ScheduleJobConfig(symbols=["BTC"], timeframe="5m", interval_minutes=1))
    assert job["id"] == "btc-5m"
    assert job["status"] == "stopped"
    listed = mgr.list_jobs()
    assert len(listed) == 1
    removed = mgr.remove_job("btc-5m")
    assert removed["id"] == "btc-5m"
    assert mgr.list_jobs() == []


def test_start_stop_background(tmp_path: Path):
    registry = tmp_path / "schedules.json"
    mgr = SchedulerManager(registry)
    mgr.add_job(
        ScheduleJobConfig(symbols=["BTC"], timeframe="5m", interval_minutes=60),
    )
    fake_results = [
        {
            "pair": "BTC/USDT",
            "combined_signal": {"stance": "中性", "action": "hold"},
            "sync": {"new_bars": 1},
        }
    ]
    with (
        patch("quant_rd_tool.scheduler_manager.run_scheduled_cycle", return_value=fake_results),
        patch("quant_rd_tool.ccxt_connectivity.require_connectivity", return_value={"ok": True}),
    ):
        started = mgr.start_job("btc-5m")
        assert started["status"] == "running"
        time.sleep(0.3)
        stopped = mgr.stop_job("btc-5m")
        assert stopped["status"] == "stopped"
        assert stopped["run_count"] >= 1


def test_persistence_reload(tmp_path: Path):
    registry = tmp_path / "schedules.json"
    mgr1 = SchedulerManager(registry)
    mgr1.add_job(ScheduleJobConfig(symbols=["ETH"], name="eth job"))
    mgr2 = SchedulerManager(registry)
    jobs = mgr2.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["symbols"] == ["ETH"]


def test_get_scheduler_manager_singleton(tmp_path: Path, monkeypatch):
    reset_scheduler_manager()
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(str(tmp_path / "data" / "crypto"))
    mgr.add_job(ScheduleJobConfig(symbols=["SOL"], timeframe="5m"))
    assert len(get_scheduler_manager(str(tmp_path / "data" / "crypto")).list_jobs()) == 1
    reset_scheduler_manager()
