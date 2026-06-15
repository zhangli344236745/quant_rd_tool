"""Filter A-share universe and batch-enqueue analysis jobs."""

from __future__ import annotations

from typing import Any, Literal

from quant_rd_tool import akshare_stocks as astk
from quant_rd_tool import report_index as rpt
from quant_rd_tool.watchlist import Watchlist

JobKind = Literal["qlib_analyze", "analyze_stock", "stock_workflow"]


def run_screener(
    *,
    q: str = "",
    has_report: bool | None = None,
    stance_in: list[str] | None = None,
    watchlist_only: bool = False,
    codes: list[str] | None = None,
    high_impact_only: bool = False,
    notice_keyword: str = "",
    page: int = 1,
    page_size: int = 50,
    data_dir: str = "data/stocks",
) -> dict[str, Any]:
    from quant_rd_tool.stock_announcement_radar import codes_with_high_impact, match_notice_keyword

    stance_set = {s.strip() for s in (stance_in or []) if s and str(s).strip()}
    report_by_code: dict[str, dict[str, Any]] = {}
    for row in rpt.list_reports(data_dir=data_dir, page=1, page_size=10_000)["items"]:
        report_by_code[row["code"]] = row

    watch_set: set[str] = set()
    if watchlist_only:
        watch_set = {w["code"] for w in Watchlist().list_items()}

    impact_codes: set[str] = set()
    if high_impact_only:
        impact_codes = codes_with_high_impact(data_dir)

    if codes:
        universe = []
        for c in codes:
            c = str(c).strip()
            if not c:
                continue
            universe.append({"code": c, "name": "", "qlib_code": c})
    else:
        universe = astk.list_a_stocks(q=q, page=1, page_size=50_000)["items"]

    rows: list[dict[str, Any]] = []
    for item in universe:
        code = item["code"]
        if watchlist_only and code not in watch_set:
            continue
        if high_impact_only and code not in impact_codes:
            continue
        if notice_keyword and not match_notice_keyword(code, notice_keyword, data_dir=data_dir):
            continue
        rep = report_by_code.get(code)
        if has_report is True and not rep:
            continue
        if has_report is False and rep:
            continue
        if stance_set and (not rep or rep.get("stance") not in stance_set):
            continue
        rows.append(
            {
                "code": code,
                "name": item.get("name"),
                "qlib_code": item.get("qlib_code"),
                "has_report": bool(rep),
                "stance": rep.get("stance") if rep else None,
                "report_mtime": rep.get("report_mtime") if rep else None,
                "high_impact": code in impact_codes if high_impact_only else None,
            }
        )

    total = len(rows)
    start = (max(1, page) - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows[start:end],
    }
