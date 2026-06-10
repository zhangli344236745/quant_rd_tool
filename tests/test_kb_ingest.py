from __future__ import annotations

from pathlib import Path


def test_content_hash_skip(tmp_path, monkeypatch):
    kb_dir = tmp_path / "kb"
    monkeypatch.setattr("quant_rd_tool.kb_ingest.project_root", lambda: tmp_path)

    root = tmp_path / "data" / "stocks" / "SH600519"
    root.mkdir(parents=True)
    (root / "report.md").write_text("# report\nhello kb", encoding="utf-8")

    from quant_rd_tool.kb_ingest import content_hash, scan_project

    assert content_hash("x") != content_hash("y")

    first = scan_project(data_dir="data", docs_dir="docs", kb_data_dir=kb_dir)
    assert first["ingested"] >= 1

    second = scan_project(data_dir="data", docs_dir="docs", kb_data_dir=kb_dir)
    assert second["skipped"] >= 1


def test_ingest_upload_md(tmp_path, monkeypatch):
    kb_dir = tmp_path / "kb"
    monkeypatch.setattr("quant_rd_tool.kb_ingest.project_root", lambda: tmp_path)

    from quant_rd_tool.kb_ingest import ingest_upload

    out = ingest_upload(b"# upload test\ncontent", "note.md", kb_data_dir=kb_dir)
    assert out["ok"] is True
    assert out.get("doc_id")
