"""A-share company directory API (akshare)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from quant_rd_tool import akshare_stocks as astk
from quant_rd_tool.akshare_data import to_ak_code
from quant_rd_tool import report_index as rpt
from quant_rd_tool import stock_screener
from quant_rd_tool.watchlist import Watchlist

router = APIRouter()


class QlibAnalyzeRequest(BaseModel):
    years: int = Field(2, ge=1, le=10, description="回溯年数（日线）")
    refresh: bool = Field(True, description="是否强制重新拉取行情")
    data_dir: str = "data/stocks"
    with_ml: bool = True
    ml_algorithm: str = Field("both", description="xgb | lgb | both")
    include_full_report: bool = Field(False, description="是否在响应中包含完整 report 对象")


def _qlib_analyze_handler(code: str, body: QlibAnalyzeRequest) -> dict:
    try:
        out = astk.run_qlib_stock_analysis(
            code,
            years=body.years,
            refresh=body.refresh,
            data_dir=body.data_dir,
            with_ml=body.with_ml,
            ml_algorithm=body.ml_algorithm,
        )
        if not body.include_full_report:
            out = {**out, "report": None}
        return out
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _enqueue_qlib(request: Request, code: str, body: QlibAnalyzeRequest) -> JSONResponse:
    store = getattr(request.app.state, "job_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Job store not initialized")
    job = store.create(
        type="qlib_analyze",
        code=code.strip(),
        payload=body.model_dump(),
    )
    return JSONResponse(status_code=202, content={"job_id": job["id"]})


@router.get("/watchlist")
def stocks_watchlist_get() -> dict[str, Any]:
    return {"items": Watchlist().list_items()}


class WatchlistAddRequest(BaseModel):
    code: str
    name: str = ""


@router.post("/watchlist")
def stocks_watchlist_add(req: WatchlistAddRequest) -> dict[str, Any]:
    row = Watchlist().add(req.code, name=req.name)
    return {"item": row}


@router.delete("/watchlist/{code}")
def stocks_watchlist_remove(code: str) -> dict[str, bool]:
    return {"removed": Watchlist().remove(code)}


@router.get("/reports")
def stocks_reports_list(
    q: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    return rpt.list_reports(q=q, page=page, page_size=page_size)


@router.get("/reports/export")
def stocks_reports_export(
    codes: str = Query("", description="逗号分隔代码，空=全部有报告标的"),
) -> Response:
    code_list = [c.strip() for c in codes.split(",") if c.strip()] or None
    try:
        payload = rpt.build_reports_zip(codes=code_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if not payload:
        raise HTTPException(status_code=404, detail="No reports to export")
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="astock-reports.zip"'},
    )


@router.get("/reports/compare")
def stocks_reports_compare(
    code_a: str = Query(..., min_length=1),
    code_b: str = Query(..., min_length=1),
) -> dict[str, Any]:
    try:
        return rpt.compare_reports(code_a, code_b)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{code}/reports/latest")
def stocks_reports_latest(code: str) -> dict[str, Any]:
    try:
        return rpt.latest_report(code)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{code}/reports/history")
def stocks_reports_history(code: str) -> dict[str, Any]:
    items = rpt.report_history(code)
    return {"code": to_ak_code(code), "items": items}


@router.get("/{code}/reports/diff")
def stocks_reports_diff(
    code: str,
    base_version: str | None = Query(None, description="归档版本 id；默认上一版"),
    compare_version: str = Query("latest"),
) -> dict[str, Any]:
    try:
        return rpt.diff_report_versions(
            code,
            base_version=base_version,
            compare_version=compare_version,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class ScreenerRequest(BaseModel):
    q: str = ""
    has_report: bool | None = None
    stance_in: list[str] = Field(default_factory=list)
    watchlist_only: bool = False
    codes: list[str] = Field(default_factory=list)
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


@router.post("/screener")
def stocks_screener(req: ScreenerRequest) -> dict[str, Any]:
    try:
        return stock_screener.run_screener(
            q=req.q,
            has_report=req.has_report,
            stance_in=req.stance_in,
            watchlist_only=req.watchlist_only,
            codes=req.codes,
            page=req.page,
            page_size=req.page_size,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/qlib-analyze/{code}")
def stocks_qlib_analyze_v2(
    code: str,
    request: Request,
    req: QlibAnalyzeRequest | None = None,
    sync: bool = Query(False, description="True 时同步执行（阻塞）"),
):
    """拉取近 N 年日线 → qlib → 技术面/风险/ML（默认异步 202）。"""
    body = req or QlibAnalyzeRequest()
    if sync:
        return _qlib_analyze_handler(code, body)
    return _enqueue_qlib(request, code, body)


@router.get("/list")
def stocks_list(
    q: str = Query("", description="代码/名称模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    try:
        return astk.list_a_stocks(q=q, page=page, page_size=page_size)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/{code}/profile")
def stocks_profile(code: str) -> dict[str, Any]:
    try:
        return astk.fetch_company_profile(code)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/{code}/management")
def stocks_management(code: str) -> dict[str, Any]:
    try:
        rows = astk.fetch_management_changes(code)
        return {"code": to_ak_code(code), "count": len(rows), "items": rows}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/{code}/news")
def stocks_news(
    code: str,
    limit: int = Query(30, ge=1, le=50),
) -> dict[str, Any]:
    try:
        rows = astk.fetch_stock_news_em(code, limit=limit)
        return {"code": to_ak_code(code), "count": len(rows), "items": rows}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/{code}/qlib-analyze")
def stocks_qlib_analyze(
    code: str,
    request: Request,
    req: QlibAnalyzeRequest | None = None,
    sync: bool = Query(False),
):
    """兼容旧路径 POST /stocks/{code}/qlib-analyze。"""
    body = req or QlibAnalyzeRequest()
    if sync:
        return _qlib_analyze_handler(code, body)
    return _enqueue_qlib(request, code, body)


@router.get("/{code}/notices")
def stocks_notices(
    code: str,
    category: str = Query("全部", description="公告类型：全部、财务报告、重大事项等"),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    try:
        rows = astk.fetch_stock_notices(code, category=category, limit=limit)
        return {"code": to_ak_code(code), "category": category, "count": len(rows), "items": rows}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
