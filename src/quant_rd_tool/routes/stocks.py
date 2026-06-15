"""A-share company directory API (akshare)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from quant_rd_tool import akshare_stocks as astk
from quant_rd_tool.akshare_data import to_ak_code, to_qlib_code
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
    with_openbb_enrichment: bool = Field(False, description="是否启用 OpenBB 宏观/行业 enrichment")


def _qlib_analyze_handler(code: str, body: QlibAnalyzeRequest) -> dict:
    try:
        out = astk.run_qlib_stock_analysis(
            code,
            years=body.years,
            refresh=body.refresh,
            data_dir=body.data_dir,
            with_ml=body.with_ml,
            ml_algorithm=body.ml_algorithm,
            with_openbb_enrichment=body.with_openbb_enrichment,
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
    watermark: bool = Query(True, description="导出 MD 加水印与 compliance manifest"),
) -> Response:
    code_list = [c.strip() for c in codes.split(",") if c.strip()] or None
    try:
        payload = rpt.build_reports_zip(codes=code_list, watermark=watermark)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if not payload:
        raise HTTPException(status_code=404, detail="No reports to export")
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="astock-reports.zip"'},
    )


@router.get("/compliance/audit")
def stocks_compliance_audit_tail(
    limit: int = Query(50, ge=1, le=500),
    run_type: str | None = Query(None),
    code: str | None = Query(None),
) -> dict[str, Any]:
    from quant_rd_tool.research_audit import tail_research_audit

    items = tail_research_audit(limit=limit, run_type=run_type, code=code)
    return {"items": items, "count": len(items)}


@router.get("/compliance/audit/verify")
def stocks_compliance_audit_verify() -> dict[str, Any]:
    from quant_rd_tool.research_audit import verify_audit_chain

    return verify_audit_chain()


@router.get("/compliance/audit/{run_id}")
def stocks_compliance_audit_get(run_id: str) -> dict[str, Any]:
    from quant_rd_tool.research_audit import get_audit_entry

    row = get_audit_entry(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Audit entry not found")
    return row


class ReportLockRequest(BaseModel):
    locked_by: str = "user"
    reason: str = ""


@router.post("/{code}/reports/{version_id}/lock")
def stocks_report_lock(code: str, version_id: str, body: ReportLockRequest) -> dict[str, Any]:
    from quant_rd_tool.research_audit import lock_report_version

    try:
        row = lock_report_version(
            code,
            version_id,
            locked_by=body.locked_by,
            reason=body.reason,
        )
        return {"locked": row}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{code}/reports/{version_id}/verify")
def stocks_report_verify(code: str, version_id: str) -> dict[str, Any]:
    from quant_rd_tool.report_versions import verify_report_version

    return verify_report_version(code, version_id)


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


@router.get("/{code}/oos-protocol")
def stocks_oos_protocol_get(
    code: str,
    algorithm: str = Query("both", pattern="^(xgb|lgb|both)$"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    data_dir: str = "data/stocks",
) -> dict[str, Any]:
    """Run qlib ML OOS fixed-split protocol for a symbol with local qlib data."""
    from quant_rd_tool.oos_protocol import compact_oos_for_ui
    from quant_rd_tool.qlib_ml import run_ml_analysis
    from quant_rd_tool.stock_storage import csv_path, load_csv, qlib_path, stock_root

    root = stock_root(data_dir, code)
    csv_file = csv_path(root)
    if not csv_file.is_file():
        raise HTTPException(status_code=404, detail=f"本地无 {code} 行情，请先运行 analyze")
    qlib_dir = qlib_path(root)
    if not qlib_dir.is_dir():
        raise HTTPException(status_code=404, detail="缺少 qlib 目录，请先运行 analyze")
    df = load_csv(csv_file)
    end = end_date or str(df["date"].max().date())
    start = start_date or str(df["date"].min().date())
    try:
        ml = run_ml_analysis(
            str(qlib_dir.resolve()),
            to_qlib_code(code),
            start_date=start,
            end_date=end,
            num_bars=len(df),
            algorithm=algorithm,  # type: ignore[arg-type]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    proto = ml.get("oos_protocol")
    if not proto and isinstance(ml.get("models"), dict):
        for model in ml["models"].values():
            if isinstance(model, dict) and model.get("oos_protocol"):
                proto = model["oos_protocol"]
                break
    return {
        "code": to_ak_code(code),
        "qlib_code": to_qlib_code(code),
        "algorithm": algorithm,
        "start_date": start,
        "end_date": end,
        "ml_enabled": ml.get("enabled"),
        "skipped": ml.get("skipped"),
        "reason": ml.get("reason"),
        "oos_protocol": proto,
        "oos_summary": compact_oos_for_ui(proto),
    }


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
    high_impact_only: bool = False
    notice_keyword: str = ""
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
            high_impact_only=req.high_impact_only,
            notice_keyword=req.notice_keyword,
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


@router.post("/list/refresh")
def stocks_list_refresh() -> dict[str, Any]:
    try:
        return astk.refresh_a_stock_list()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


class StockScheduleCreateRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list, description="A 股代码列表；自选模式可留空")
    name: str = ""
    id: str = ""
    interval_minutes: int = Field(1440, ge=5, le=10080, description="调度间隔（分钟），默认 1440=每日")
    years: int = Field(2, ge=1, le=10)
    data_dir: str = "data/stocks"
    with_ml: bool = True
    ml_algorithm: str = "both"
    with_openbb: bool = False
    use_watchlist: bool = Field(False, description="True 时分析自选列表全部标的")
    job_type: str = Field(
        "",
        description="stock_qlib | stock_watchlist | stock_announcements；留空时按 use_watchlist 推断",
    )
    auto_start: bool = False


@router.get("/schedules")
def stocks_schedules_list(data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    jobs = mgr.list_jobs()
    return {"count": len(jobs), "jobs": jobs}


@router.get("/schedules/{job_id}")
def stocks_schedules_get(job_id: str, data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    job = mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"未找到任务: {job_id}")
    return job


@router.post("/schedules")
def stocks_schedules_create(req: StockScheduleCreateRequest) -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import ScheduleJobConfig, get_scheduler_manager

    if req.job_type in ("stock_qlib", "stock_watchlist", "stock_announcements"):
        job_type = req.job_type
    else:
        job_type = "stock_watchlist" if req.use_watchlist else "stock_qlib"
    use_watchlist = req.use_watchlist or job_type in ("stock_watchlist", "stock_announcements")
    mgr = get_scheduler_manager(req.data_dir)
    cfg = ScheduleJobConfig(
        symbols=req.symbols,
        name=req.name,
        id=req.id,
        timeframe="1d",
        interval_minutes=req.interval_minutes,
        data_dir=req.data_dir,
        with_ml=req.with_ml,
        ml_algorithm=req.ml_algorithm,
        job_type=job_type,
        years=req.years,
        with_openbb=req.with_openbb,
        use_watchlist=use_watchlist,
    )
    try:
        return mgr.add_job(cfg, auto_start=req.auto_start)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/ops/summary")
def stock_ops_summary(
    data_dir: str = "data/stocks",
    stale_calendar_days: int = Query(5, ge=1, le=30),
) -> dict[str, Any]:
    """Schedules, data freshness, connectivity, and announcement digest for A-share ops."""
    from quant_rd_tool.stock_ops import build_stock_ops_summary

    return build_stock_ops_summary(data_dir=data_dir, stale_calendar_days=stale_calendar_days)


@router.get("/ops/connectivity")
def stock_ops_connectivity(data_dir: str = "data/stocks", probe_code: str = "600519") -> dict[str, Any]:
    from quant_rd_tool.stock_ops import check_akshare_connectivity

    return check_akshare_connectivity(probe_code=probe_code, data_dir=data_dir)


@router.post("/schedules/{job_id}/start")
def stocks_schedules_start(job_id: str, data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    try:
        return mgr.start_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/schedules/{job_id}/stop")
def stocks_schedules_stop(job_id: str, data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    try:
        return mgr.stop_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/schedules/{job_id}/run-once")
def stocks_schedules_run_once(job_id: str, data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    try:
        return mgr.run_once(job_id, precheck_connectivity=False)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.delete("/schedules/{job_id}")
def stocks_schedules_delete(job_id: str, data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    try:
        return mgr.remove_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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


class StockZiplineSyncRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["600519", "000001"])
    data_dir: str = "data/stocks"
    backfill_days: int = Field(800, ge=30, le=3000)


class StockVarHolding(BaseModel):
    symbol: str
    notional_cny: float | None = Field(None, ge=0)
    shares: float | None = None


class StockVarPortfolioRequest(BaseModel):
    holdings: list[StockVarHolding] = Field(..., min_length=1)
    data_dir: str = "data/stocks"
    lookback_bars: int = Field(252, ge=30, le=2000)
    horizon_days: int = Field(1, ge=1, le=30)
    confidence: str = "0.95,0.99"
    mc_n_sims: int = Field(10_000, ge=1000, le=100_000)
    mc_seed: int = 42


class StockZiplineComboLeg(BaseModel):
    strategy: str
    params: dict[str, Any] | None = None
    weight: float = Field(1.0, gt=0)


class StockZiplineBacktestRequest(BaseModel):
    symbol: str = "600519"
    strategy: str = "ma_crossover"
    start: str = "2024-01-01"
    end: str = "2026-06-03"
    capital_base: float = Field(100_000.0, gt=0)
    data_dir: str = "data/stocks"
    strategy_params: dict[str, Any] | None = None
    lookback_days: int = Field(800, ge=30, le=3000)
    sync_first: bool = False
    engine: str = Field("auto", pattern="^(auto|pandas|zipline)$")
    force_reingest: bool = False
    timeframe: str = "1d"
    strategy_combo: list[StockZiplineComboLeg] | None = None
    combo_mode: str = Field("vote", pattern="^(vote|and|or|weighted)$")


@router.get("/var/symbol")
def stock_var_symbol(
    symbol: str = "600519",
    notional_cny: float = 0.0,
    data_dir: str = "data/stocks",
    lookback_bars: int = 252,
    horizon_days: int = 1,
    confidence: str = "0.95,0.99",
    mc_n_sims: int = 10_000,
    mc_seed: int = 42,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_var import parse_confidence_levels
    from quant_rd_tool.stock_var import build_symbol_var_report

    levels = parse_confidence_levels(confidence)
    try:
        return build_symbol_var_report(
            symbol=symbol,
            notional_cny=notional_cny,
            data_dir=data_dir,
            lookback_bars=min(lookback_bars, 2000),
            horizon_days=horizon_days,
            confidence_levels=levels,
            mc_n_sims=mc_n_sims,
            mc_seed=mc_seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/var/symbol/history")
def stock_var_symbol_history(
    symbol: str = "600519",
    window: int = 60,
    confidence: float = 0.99,
    data_dir: str = "data/stocks",
    lookback_bars: int = 252,
    horizon_days: int = 1,
    notional_cny: float = 0.0,
) -> dict[str, Any]:
    from quant_rd_tool.stock_var import build_symbol_var_history

    try:
        return build_symbol_var_history(
            symbol=symbol,
            window=min(window, 500),
            confidence=confidence,
            data_dir=data_dir,
            lookback_bars=min(lookback_bars, 2000),
            horizon_days=horizon_days,
            notional_cny=notional_cny,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/var/portfolio")
def stock_var_portfolio_post(req: StockVarPortfolioRequest) -> dict[str, Any]:
    from quant_rd_tool.crypto_var import parse_confidence_levels
    from quant_rd_tool.stock_var import build_portfolio_var_report

    levels = parse_confidence_levels(req.confidence)
    holdings = [h.model_dump() for h in req.holdings]
    try:
        return build_portfolio_var_report(
            holdings,
            data_dir=req.data_dir,
            lookback_bars=req.lookback_bars,
            horizon_days=req.horizon_days,
            confidence_levels=levels,
            mc_n_sims=req.mc_n_sims,
            mc_seed=req.mc_seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/var/portfolio")
def stock_var_portfolio_get(
    symbols: str = "600519,000001",
    notionals: str | None = None,
    data_dir: str = "data/stocks",
    lookback_bars: int = 252,
    horizon_days: int = 1,
    confidence: str = "0.95,0.99",
    mc_n_sims: int = 10_000,
    mc_seed: int = 42,
) -> dict[str, Any]:
    from quant_rd_tool.crypto_var import parse_confidence_levels
    from quant_rd_tool.stock_var import build_portfolio_var_report

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    notional_list: list[float | None] = []
    if notionals:
        for part in notionals.split(","):
            part = part.strip()
            notional_list.append(float(part) if part else None)
    holdings = []
    for i, sym in enumerate(sym_list):
        row: dict[str, Any] = {"symbol": sym}
        if i < len(notional_list) and notional_list[i] is not None:
            row["notional_cny"] = notional_list[i]
        holdings.append(row)
    levels = parse_confidence_levels(confidence)
    try:
        return build_portfolio_var_report(
            holdings,
            data_dir=data_dir,
            lookback_bars=min(lookback_bars, 2000),
            horizon_days=horizon_days,
            confidence_levels=levels,
            mc_n_sims=mc_n_sims,
            mc_seed=mc_seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class StockWorkflowStep(BaseModel):
    id: str
    enabled: bool = True
    order: int = 0
    params: dict[str, Any] = Field(default_factory=dict)


class StockWorkflowTemplateBody(BaseModel):
    id: str | None = None
    name: str = "A股 Workflow"
    symbol_default: str = "600519"
    timeframe: str = "1d"
    data_dir: str = "data/stocks"
    steps: list[StockWorkflowStep] = Field(default_factory=list)


class StockWorkflowRunRequest(BaseModel):
    symbol: str | None = None
    timeframe: str | None = None
    template_id: str | None = None
    template: StockWorkflowTemplateBody | None = None
    steps: list[StockWorkflowStep] | None = None
    data_dir: str = "data/stocks"
    refresh_ohlcv: bool = True


class AnnouncementScanRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    use_watchlist: bool = True
    notice_limit: int = Field(15, ge=5, le=50)
    min_score: int = Field(40, ge=0, le=100)


@router.get("/workflow/steps")
def stock_workflow_steps_get() -> dict[str, Any]:
    from quant_rd_tool.stock_workflow import list_step_catalog

    return {"steps": list_step_catalog()}


@router.get("/workflow/templates")
def stock_workflow_templates_get(data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.stock_workflow_storage import list_templates

    items = list_templates(data_dir)
    return {"count": len(items), "templates": items}


@router.post("/workflow/templates")
def stock_workflow_templates_post(
    body: StockWorkflowTemplateBody,
    data_dir: str = "data/stocks",
) -> dict[str, Any]:
    from quant_rd_tool.stock_workflow import normalize_template_steps
    from quant_rd_tool.stock_workflow_storage import upsert_template

    payload = body.model_dump()
    payload["data_dir"] = data_dir
    payload["steps"] = normalize_template_steps([s.model_dump() for s in body.steps] or [])
    tpl = upsert_template(data_dir, payload)
    return {"ok": True, "template": tpl}


@router.put("/workflow/templates/{template_id}")
def stock_workflow_templates_put(
    template_id: str,
    body: StockWorkflowTemplateBody,
    data_dir: str = "data/stocks",
) -> dict[str, Any]:
    from quant_rd_tool.stock_workflow import normalize_template_steps
    from quant_rd_tool.stock_workflow_storage import upsert_template

    payload = body.model_dump()
    payload["id"] = template_id
    payload["data_dir"] = data_dir
    payload["steps"] = normalize_template_steps([s.model_dump() for s in body.steps] or [])
    tpl = upsert_template(data_dir, payload)
    return {"ok": True, "template": tpl}


@router.delete("/workflow/templates/{template_id}")
def stock_workflow_templates_delete(template_id: str, data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.stock_workflow_storage import delete_template

    ok = delete_template(data_dir, template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}


@router.post("/workflow/templates/{template_id}/duplicate")
def stock_workflow_templates_duplicate(
    template_id: str,
    data_dir: str = "data/stocks",
    name: str | None = None,
) -> dict[str, Any]:
    from quant_rd_tool.stock_workflow_storage import duplicate_template

    tpl = duplicate_template(data_dir, template_id, name=name)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True, "template": tpl}


@router.post("/workflow/run")
def stock_workflow_run_post(req: StockWorkflowRunRequest) -> dict[str, Any]:
    from quant_rd_tool.stock_workflow import resolve_template_for_run, run_workflow

    data_dir = req.data_dir
    try:
        tpl = resolve_template_for_run(
            data_dir=data_dir,
            template_id=req.template_id,
            template=req.template.model_dump() if req.template else None,
            timeframe=req.timeframe,
            steps=[s.model_dump() for s in req.steps] if req.steps else None,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    sym = (req.symbol or tpl.get("symbol_default") or "600519").strip()
    try:
        return run_workflow(
            symbol=sym,
            template=tpl,
            data_dir=data_dir,
            refresh_ohlcv=req.refresh_ohlcv,
            save=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/workflow/runs")
def stock_workflow_runs_get(data_dir: str = "data/stocks", limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    from quant_rd_tool.stock_workflow_storage import list_runs

    runs = list_runs(data_dir, limit=limit)
    return {"count": len(runs), "runs": runs}


@router.get("/workflow/runs/{run_id}")
def stock_workflow_run_get(run_id: str, data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.stock_workflow_storage import load_run

    run = load_run(data_dir, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/announcements/digest")
def stock_announcements_digest_get(data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.stock_announcement_radar import load_digest

    digest = load_digest(data_dir)
    return {"digest": digest}


@router.get("/announcements/items")
def stock_announcements_items_get(
    data_dir: str = "data/stocks",
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    from quant_rd_tool.stock_announcement_radar import tail_items

    items = tail_items(data_dir=data_dir, limit=limit)
    return {"count": len(items), "items": items}


@router.post("/announcements/scan")
def stock_announcements_scan_post(req: AnnouncementScanRequest) -> dict[str, Any]:
    from quant_rd_tool.stock_announcement_radar import run_announcement_scan

    try:
        return run_announcement_scan(
            data_dir="data/stocks",
            symbols=req.symbols,
            use_watchlist=req.use_watchlist,
            notice_limit=req.notice_limit,
            min_score=req.min_score,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/zipline/status")
def stock_zipline_status_get(
    data_dir: str = "data/stocks",
    symbols: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    from quant_rd_tool.stock_zipline_lab import lab_status

    sym_list = [s.strip() for s in symbols.split(",")] if symbols else None
    return lab_status(data_dir, sym_list, timeframe=timeframe)


@router.get("/zipline/strategies")
def stock_zipline_strategies_get() -> dict[str, Any]:
    from quant_rd_tool.stock_zipline_lab import get_strategies

    return {"strategies": get_strategies()}


@router.post("/zipline/setup-venv")
def stock_zipline_setup_venv_post() -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_env import ensure_zipline_venv, zipline_venv_ready

    try:
        py = ensure_zipline_venv()
        ok, err = zipline_venv_ready()
        return {"ok": ok, "python": str(py), "error": err}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/zipline/sync")
def stock_zipline_sync_post(req: StockZiplineSyncRequest) -> dict[str, Any]:
    from quant_rd_tool.stock_zipline_lab import sync_ohlcv_for_lab

    try:
        return sync_ohlcv_for_lab(req.symbols, data_dir=req.data_dir, backfill_days=req.backfill_days)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/zipline/backtest")
def stock_zipline_backtest_post(req: StockZiplineBacktestRequest) -> dict[str, Any]:
    from quant_rd_tool.stock_zipline_lab import run_lab_backtest

    combo_legs = None
    if req.strategy_combo:
        combo_legs = [leg.model_dump() for leg in req.strategy_combo]

    try:
        return run_lab_backtest(
            symbol=req.symbol,
            data_dir=req.data_dir,
            strategy_id=req.strategy,
            start=req.start,
            end=req.end,
            capital_base=req.capital_base,
            strategy_params=req.strategy_params,
            lookback_days=req.lookback_days,
            sync_first=req.sync_first,
            engine=req.engine,
            force_reingest=req.force_reingest,
            timeframe=req.timeframe,
            strategy_combo=combo_legs,
            combo_mode=req.combo_mode,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/zipline/runs")
def stock_zipline_runs_get(
    data_dir: str = "data/stocks", limit: int = Query(20, ge=1, le=100)
) -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_storage import list_runs

    items = list_runs(data_dir, limit=limit)
    return {"count": len(items), "runs": items}


@router.get("/zipline/runs/{run_id}")
def stock_zipline_run_get(run_id: str, data_dir: str = "data/stocks") -> dict[str, Any]:
    from quant_rd_tool.crypto_zipline_storage import load_run

    run = load_run(data_dir, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/zipline/data/export")
def stock_zipline_data_export(
    symbol: str = Query("600519"),
    data_dir: str = "data/stocks",
    timeframe: str = "1d",
    start: str | None = None,
    end: str | None = None,
    lookback_days: int = Query(800, ge=30, le=3000),
    format: str = Query("csv", pattern="^(csv|zip)$"),
    run_id: str | None = None,
) -> Response:
    from quant_rd_tool.stock_zipline_export import (
        build_export_zip,
        export_filename,
        export_ohlcv_dataframe,
    )

    try:
        if format == "zip":
            content = build_export_zip(
                symbol,
                data_dir=data_dir,
                timeframe=timeframe,
                start=start,
                end=end,
                lookback_days=lookback_days,
                run_id=run_id,
            )
            fname = export_filename(symbol, timeframe, ext="zip")
            return Response(
                content=content,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{fname}"'},
            )
        df = export_ohlcv_dataframe(
            symbol,
            data_dir=data_dir,
            timeframe=timeframe,
            start=start,
            end=end,
            lookback_days=lookback_days,
        )
        fname = export_filename(symbol, timeframe, ext="csv")
        return Response(
            content=df.to_csv(index=False),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


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
