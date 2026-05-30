def test_runner_executes_qlib_job(tmp_path, monkeypatch):
    from quant_rd_tool.job_store import JobStore
    from quant_rd_tool.job_runner import JobRunner

    store = JobStore(tmp_path / "jobs.db")
    data_dir = tmp_path / "data" / "stocks"
    j = store.create(type="qlib_analyze", code="600519", payload={"years": 1, "with_ml": False})

    def fake_run(code, **kw):
        root = data_dir / "SH600519"
        root.mkdir(parents=True)
        (root / "report.json").write_text('{"symbol":"SH600519"}', encoding="utf-8")
        return {"code": code, "qlib_code": "SH600519", "summary": {}}

    monkeypatch.setattr("quant_rd_tool.job_runner.astk.run_qlib_stock_analysis", fake_run)
    runner = JobRunner(store, data_dir=str(data_dir))
    runner.run_once()
    got = store.get(j["id"])
    assert got["status"] == "done"
    assert "report.json" in (got.get("result_path") or "")
