import json

from quant_rd_tool.report_versions import (
    archive_report_if_exists,
    diff_report_versions,
    list_report_versions,
)
from quant_rd_tool.stock_storage import report_json_path, stock_root


def test_archive_and_diff(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = stock_root("data/stocks", "600519")
    root.mkdir(parents=True)
    old = {
        "symbol": "SH600519",
        "narrative": {"stance": "谨慎", "summary": "old"},
        "analysis": {"technical": {"rsi_14": 40}, "returns": {"20d": -0.01}},
    }
    report_json_path(root).write_text(json.dumps(old), encoding="utf-8")
    vid = archive_report_if_exists(root)
    assert vid
    new = {
        "symbol": "SH600519",
        "narrative": {"stance": "偏多", "summary": "new"},
        "analysis": {"technical": {"rsi_14": 55}, "returns": {"20d": 0.02}},
    }
    report_json_path(root).write_text(json.dumps(new), encoding="utf-8")
    versions = list_report_versions("600519", data_dir="data/stocks")
    assert len(versions) >= 2
    diff = diff_report_versions("600519", data_dir="data/stocks")
    assert diff["base_stance"] == "谨慎"
    assert diff["compare_stance"] == "偏多"
    assert any(c["field"] == "stance" for c in diff["changes"])
