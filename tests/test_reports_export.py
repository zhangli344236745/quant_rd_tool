def test_build_reports_zip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data" / "stocks" / "SH600519"
    root.mkdir(parents=True)
    (root / "report.json").write_text('{"symbol":"SH600519"}', encoding="utf-8")
    (root / "report.md").write_text("# hi", encoding="utf-8")

    from quant_rd_tool.report_index import build_reports_zip

    blob = build_reports_zip(data_dir="data/stocks")
    assert len(blob) > 100
    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(blob)) as zf:
        names = zf.namelist()
    assert "SH600519/report.json" in names
    assert "SH600519/report.md" in names
