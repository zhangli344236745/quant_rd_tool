import pytest

from quant_rd_tool.job_store import JobStore


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "jobs.db")


def test_create_and_get(store):
    j = store.create(type="qlib_analyze", code="600519", payload={"years": 2})
    got = store.get(j["id"])
    assert got["status"] == "queued"
    assert got["code"] == "600519"


def test_transition_running_done(store):
    j = store.create(type="qlib_analyze", code="600519", payload={})
    store.mark_running(j["id"], message="fetch")
    store.mark_done(j["id"], result_path="data/stocks/SH600519/report.json", message="ok")
    got = store.get(j["id"])
    assert got["status"] == "done"
    assert got["progress"] == 1.0


def test_list_filter_status(store):
    store.create(type="qlib_analyze", code="1", payload={})
    j2 = store.create(type="qlib_analyze", code="2", payload={})
    store.mark_failed(j2["id"], error="boom")
    rows = store.list_jobs(status="failed")
    assert len(rows) == 1
    assert rows[0]["code"] == "2"


def test_cancel_only_queued(store):
    j = store.create(type="qlib_analyze", code="1", payload={})
    assert store.mark_cancelled(j["id"]) is True
    assert store.get(j["id"])["status"] == "cancelled"
    j2 = store.create(type="qlib_analyze", code="2", payload={})
    store.mark_running(j2["id"])
    assert store.mark_cancelled(j2["id"]) is False


def test_claim_next_queued(store):
    j1 = store.create(type="qlib_analyze", code="a", payload={})
    store.create(type="qlib_analyze", code="b", payload={})
    claimed = store.claim_next_queued()
    assert claimed is not None
    assert claimed["id"] == j1["id"]
    assert claimed["status"] == "running"
