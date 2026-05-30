from quant_rd_tool.job_store import JobStore


def test_job_events_and_retry(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create(type="qlib_analyze", code="600519", payload={"max_attempts": 2, "_attempt": 1})
    jid = job["id"]
    store.append_event(jid, "info", "step1", progress=0.1)
    evs = store.list_events(jid)
    assert len(evs) == 1
    store.schedule_retry(jid, error="boom")
    got = store.get(jid)
    assert got["status"] == "queued"
    assert got["payload"]["_attempt"] == 2
