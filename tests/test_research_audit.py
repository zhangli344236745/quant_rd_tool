import json

from quant_rd_tool.report_versions import archive_report_if_exists, verify_report_version
from quant_rd_tool.research_audit import (
    lock_report_version,
    record_research_run,
    tail_research_audit,
    verify_audit_chain,
    watermark_markdown,
)
from quant_rd_tool.report_index import build_reports_zip
from quant_rd_tool.stock_storage import report_json_path, stock_root


def test_audit_chain_links(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = record_research_run(
        "analyze_stock",
        code="600519",
        inputs={"years": 2},
        outputs_summary={"stance": "偏多"},
    )
    b = record_research_run(
        "portfolio_backtest",
        inputs={"symbols": ["600519"]},
        outputs_summary={"total_return": 0.1},
    )
    assert a["entry_hash"] != b["entry_hash"]
    assert b["prev_hash"] == a["entry_hash"]
    verify = verify_audit_chain()
    assert verify["valid"] is True
    assert verify["entries"] == 2


def test_tail_and_get_audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    row = record_research_run(
        "zipline_lab",
        code="600519",
        inputs={"strategy": "ma_crossover"},
        outputs_summary={"total_return": 0.05},
        run_id="fixed-run-id",
    )
    items = tail_research_audit(run_type="zipline_lab")
    assert len(items) == 1
    assert items[0]["run_id"] == row["run_id"]


def test_report_lock_and_verify(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = stock_root("data/stocks", "600519")
    root.mkdir(parents=True)
    report = {
        "symbol": "SH600519",
        "narrative": {"stance": "谨慎", "summary": "test"},
        "generated_at": "2026-06-15T00:00:00+00:00",
    }
    report_json_path(root).write_text(json.dumps(report), encoding="utf-8")
    vid = archive_report_if_exists(root)
    assert vid
    verify = verify_report_version("600519", vid, data_dir="data/stocks")
    assert verify["valid"] is True
    locked = lock_report_version("600519", vid, reason="sign-off")
    assert locked["version_id"] == vid
    verify2 = verify_report_version("600519", vid, data_dir="data/stocks")
    assert verify2["locked"] is True


def test_watermarked_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = stock_root("data/stocks", "600519")
    root.mkdir(parents=True)
    report_json_path(root).write_text(
        json.dumps({"symbol": "SH600519", "narrative": {"stance": "中性"}}),
        encoding="utf-8",
    )
    (root / "report.md").write_text("# Report\nbody", encoding="utf-8")
    blob = build_reports_zip(codes=["600519"], watermark=True)
    assert blob
    import zipfile
    import io

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        assert any(n.endswith("report.md") for n in names)
        assert "compliance/manifest.json" in names
        md = zf.read([n for n in names if n.endswith("report.md")][0]).decode("utf-8")
        assert "研究用途" in md


def test_watermark_markdown_prefix():
    out = watermark_markdown("# hi", meta={"content_hash": "abc"})
    assert "研究用途" in out
    assert "abc" in out
    assert out.endswith("# hi")
