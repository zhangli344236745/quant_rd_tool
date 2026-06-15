from quant_rd_tool.stock_announcement_radar import score_text, tail_items


def test_score_text_keywords():
    score, hits = score_text("公司发布业绩预增公告")
    assert score == 80
    assert "业绩预增" in hits


def test_score_text_no_match():
    score, hits = score_text("日常经营情况说明")
    assert score == 0
    assert hits == []


def test_tail_items_empty(tmp_path):
    rows = tail_items(data_dir=str(tmp_path / "stocks"), limit=10)
    assert rows == []
