from quant_rd_tool.kb_chunking import split_json_report, split_text


def test_split_text_overlap():
    text = "a" * 600
    chunks = split_text(text, chunk_size=200, overlap=50)
    assert len(chunks) >= 3
    assert all(len(c) <= 200 for c in chunks)


def test_split_json_report_sections():
    data = {"narrative": {"summary": "ok"}, "analysis": {"rsi": 55}}
    sections = split_json_report(data)
    assert len(sections) == 2
    assert "narrative" in sections[0]
    assert "analysis" in sections[1]
