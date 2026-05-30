def test_backtest_job_saves_result(tmp_path, monkeypatch):
    from quant_rd_tool.job_store import JobStore
    from quant_rd_tool.job_runner import JobRunner

    monkeypatch.chdir(tmp_path)
    store = JobStore(tmp_path / "jobs.db")

    def fake_backtest(*args, **kwargs):
        return {
            "symbols": ["600519"],
            "advice": {"stance": "中性"},
            "metrics": {"sharpe": 1.2},
            "strategy_desc": "test",
        }

    monkeypatch.setattr("quant_rd_tool.backtest_engine.run_backtest", fake_backtest)

    j = store.create(type="backtest_run", code="600519", payload={"symbols": ["600519"]})
    runner = JobRunner(store)
    runner.run_once()
    got = store.get(j["id"])
    assert got["status"] == "done"
    assert got["result_path"]
