def test_recover_stale_running(tmp_path):
    from quant_rd_tool.job_store import JobStore

    store = JobStore(tmp_path / "jobs.db")
    j = store.create(type="qlib_analyze", code="1", payload={})
    store.mark_running(j["id"])
    n = store.recover_stale_running()
    assert n == 1
    got = store.get(j["id"])
    assert got["status"] == "failed"
    assert "interrupted" in (got.get("error") or "")
