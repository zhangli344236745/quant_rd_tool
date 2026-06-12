from __future__ import annotations

import time

import pytest

from quant_rd_tool.crypto_bot_scheduler import BotScheduler


class _FakeBot:
    def __init__(self, results=None, fail=False):
        self._results = results or [{"message": "ok", "order": None}]
        self._i = 0
        self._fail = fail

    def run_once(self):
        if self._fail:
            raise RuntimeError("boom")
        r = self._results[min(self._i, len(self._results) - 1)]
        self._i += 1
        return r


def _scheduler_with(bot):
    sched = BotScheduler()
    sched.set_factory("spot", lambda _id, _cfg: bot)
    return sched


def test_register_and_run_managed_once():
    sched = _scheduler_with(_FakeBot([{"message": "hi", "order": {"side": "buy"}}]))
    sched.register(bot_id="b1", kind="spot", config={"symbol": "BTC"}, interval_minutes=5)
    result = sched.run_managed_once("b1")
    assert result["message"] == "hi"
    st = sched.status_one("b1")
    assert st["run_count"] == 1
    assert st["last_error"] is None


def test_run_records_error():
    sched = _scheduler_with(_FakeBot(fail=True))
    sched.register(bot_id="b1", kind="spot", config={}, interval_minutes=5)
    with pytest.raises(RuntimeError):
        sched.run_managed_once("b1")
    st = sched.status_one("b1")
    assert st["error_count"] == 1
    assert st["status"] == "error"
    assert "boom" in st["last_error"]


def test_invalid_interval_rejected():
    sched = BotScheduler()
    with pytest.raises(ValueError):
        sched.register(bot_id="b1", kind="spot", config={}, interval_minutes=0)


def test_unregistered_bot_raises():
    sched = BotScheduler()
    with pytest.raises(KeyError):
        sched.status_one("nope")


def test_trim_result_drops_heavy_fields():
    heavy = {
        "message": "ok",
        "analysis": {"big": 1},
        "equity_curve": [1, 2],
        "performance": {"equity": 100},
    }
    sched = _scheduler_with(_FakeBot([heavy]))
    sched.register(bot_id="b1", kind="spot", config={}, interval_minutes=5)
    sched.run_managed_once("b1")
    last = sched.status_one("b1")["last_result"]
    assert "analysis" not in last
    assert "equity_curve" not in last
    assert last["performance"]["equity"] == 100


def test_start_stop_thread_lifecycle():
    sched = _scheduler_with(_FakeBot())
    sched.register(bot_id="b1", kind="spot", config={}, interval_minutes=1)
    sched.start("b1")
    # give the loop a moment to run at least once
    for _ in range(50):
        if sched.status_one("b1")["run_count"] >= 1:
            break
        time.sleep(0.02)
    assert sched.status_one("b1")["status"] == "running"
    sched.stop("b1")
    assert sched.status_one("b1")["status"] == "stopped"


def test_perp_factory_via_scheduler():
    class _PerpFake:
        def run_once(self):
            return {"message": "perp ok", "perp_action": "hold"}

    sched = BotScheduler()
    sched.set_factory("perp", lambda _id, _cfg: _PerpFake())
    sched.register(bot_id="p1", kind="perp", config={"base": "BTC", "dry_run": True}, interval_minutes=5)
    result = sched.run_managed_once("p1")
    assert result["message"] == "perp ok"
    assert sched.status_one("p1")["kind"] == "perp"


def test_cannot_reregister_running_bot():
    sched = _scheduler_with(_FakeBot())
    sched.register(bot_id="b1", kind="spot", config={}, interval_minutes=1)
    sched.start("b1")
    try:
        with pytest.raises(ValueError):
            sched.register(bot_id="b1", kind="spot", config={}, interval_minutes=2)
    finally:
        sched.stop("b1")
