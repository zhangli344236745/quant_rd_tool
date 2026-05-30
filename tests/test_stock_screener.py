import json

from fastapi.testclient import TestClient

from quant_rd_tool.main import app
from quant_rd_tool.stock_screener import run_screener
from quant_rd_tool.stock_storage import report_json_path, stock_root


def test_screener_has_report_filter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = stock_root("data/stocks", "600519")
    root.mkdir(parents=True)
    report_json_path(root).write_text(
        json.dumps({"narrative": {"stance": "偏多", "summary": "x"}}),
        encoding="utf-8",
    )

    out = run_screener(codes=["600519", "000001"], has_report=True, page_size=10)
    assert out["total"] == 1
    assert out["items"][0]["code"] == "600519"


def test_screener_enqueue_http(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = stock_root("data/stocks", "600519")
    root.mkdir(parents=True)
    report_json_path(root).write_text(
        json.dumps({"narrative": {"stance": "偏多", "summary": "x"}}),
        encoding="utf-8",
    )
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/jobs/screener-enqueue",
            json={"codes": ["600519"], "limit": 5, "job_type": "qlib_analyze"},
        )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["enqueued"] == 1
    assert len(body["job_ids"]) == 1
