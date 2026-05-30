import json


def test_list_reports_and_latest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data" / "stocks" / "SH600519"
    root.mkdir(parents=True)
    (root / "report.json").write_text(
        '{"symbol":"SH600519","narrative":{"stance":"偏多","summary":"s"}}',
        encoding="utf-8",
    )
    (root / "report.md").write_text("# hi", encoding="utf-8")

    from quant_rd_tool.report_index import latest_report, list_reports

    out = list_reports(data_dir="data/stocks")
    assert out["total"] == 1
    assert out["items"][0]["qlib_code"] == "SH600519"
    assert out["items"][0]["stance"] == "偏多"

    latest = latest_report("600519", data_dir="data/stocks")
    assert latest["summary"] == "s"
    assert latest["markdown"] == "# hi"


def test_compare_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for sym, stance in (("SH600519", "偏多"), ("SZ000001", "谨慎")):
        root = tmp_path / "data" / "stocks" / sym
        root.mkdir(parents=True)
        (root / "report.json").write_text(
            json.dumps(
                {
                    "symbol": sym,
                    "narrative": {"stance": stance, "summary": f"sum-{sym}"},
                    "analysis": {"technical": {"rsi_14": 50}, "returns": {"20d": 0.01}},
                    "openbb": {"macro": {"available": True, "summary": "宏观 ok"}},
                }
            ),
            encoding="utf-8",
        )

    from quant_rd_tool.report_index import compare_reports

    out = compare_reports("600519", "000001", data_dir="data/stocks")
    assert out["a"]["stance"] == "偏多"
    assert out["b"]["stance"] == "谨慎"
    assert out["a"]["technical"]["rsi_14"] == 50
    assert out["a"]["macro_summary"] == "宏观 ok"
