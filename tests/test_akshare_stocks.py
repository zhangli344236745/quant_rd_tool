from unittest.mock import patch

import pandas as pd

from quant_rd_tool import akshare_stocks as astk
from quant_rd_tool.akshare_data import _filter_date_range, _normalize_hist


def test_filter_date_range_canonicalizes_chinese_columns():
    df = pd.DataFrame(
        {
            "日期": ["2024-01-02", "2024-01-03", "2024-02-01"],
            "收盘": [10.0, 10.5, 11.0],
            "开盘": [9.8, 10.1, 10.8],
            "最高": [10.2, 10.6, 11.2],
            "最低": [9.7, 10.0, 10.7],
            "成交量": [1000, 1100, 900],
        }
    )
    filtered = _filter_date_range(df, "2024-01-01", "2024-01-31")
    normalized = _normalize_hist(filtered, "SZ300750")
    assert len(normalized) == 2
    assert "date" in normalized.columns
    assert normalized["symbol"].iloc[0] == "SZ300750"


def test_list_a_stocks_search():
    items = [
        {"code": "600519", "name": "贵州茅台", "qlib_code": "SH600519"},
        {"code": "000001", "name": "平安银行", "qlib_code": "SZ000001"},
    ]
    with patch.object(astk, "_fetch_a_stock_list_raw", return_value=items):
        out = astk.list_a_stocks(q="茅台", page=1, page_size=10)
    assert out["total"] == 1
    assert out["items"][0]["code"] == "600519"


def test_fetch_company_profile_merges():
    with (
        patch.object(
            astk,
            "fetch_stock_profile_em",
            return_value=[
                {"key": "股票简称", "value": "贵州茅台"},
                {"key": "行业", "value": "白酒"},
            ],
        ),
        patch.object(
            astk,
            "fetch_stock_profile_cninfo",
            return_value=[{"key": "A股简称", "value": "贵州茅台"}],
        ),
    ):
        prof = astk.fetch_company_profile("600519")
    assert prof["code"] == "600519"
    assert prof["name"] == "贵州茅台"


def test_df_records_limit():
    df = pd.DataFrame({"a": [1, 2, 3]})
    rows = astk._df_records(df, limit=2)
    assert len(rows) == 2


def test_summarize_qlib_report():
    report = {
        "symbol": "SH600519",
        "narrative": {
            "stance": "偏多",
            "summary": "测试摘要",
            "observations": ["观察1"],
            "risks": ["风险1"],
            "disclaimer": "免责声明",
        },
        "analysis": {
            "period": {"start": "2024-01-01", "end": "2026-01-01", "bars": 400},
            "price": {"latest_close": 100},
        },
        "ml_analysis": {"skipped": True, "reason": "demo"},
    }
    s = astk.summarize_qlib_report(report)
    assert s["stance"] == "偏多"
    assert s["ml_skipped"] is True


def test_run_qlib_stock_analysis_delegates():
    fake_report = {
        "symbol": "SH600519",
        "narrative": {"stance": "中性", "summary": "", "observations": [], "risks": []},
        "analysis": {"period": {}},
        "ml_analysis": {},
        "markdown": "# test",
        "fetched_new_data": True,
    }
    with patch("quant_rd_tool.stock_analysis.analyze_stock", return_value=fake_report):
        out = astk.run_qlib_stock_analysis("600519", years=2, refresh=True)
    assert out["code"] == "600519"
    assert out["years"] == 2
    assert out["summary"]["stance"] == "中性"
