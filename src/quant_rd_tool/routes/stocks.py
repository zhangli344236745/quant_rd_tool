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
