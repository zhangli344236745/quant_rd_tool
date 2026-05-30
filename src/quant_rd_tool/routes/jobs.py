"""Async job API for stock analyze / qlib tasks."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()


class QlibJobRequest(BaseModel):
    code: str = Field(..., description="股票代码")
    years: int = Field(2, ge=1, le=10)
    refresh: bool = True
    data_dir: str = "data/stocks"
    with_ml: bool = True
    ml_algorithm: str = "both"
    include_full_report: bool = False
    max_attempts: int = Field(1, ge=1, le=5)


class AnalyzeStockJobRequest(BaseModel):
    code: str
    start_date: str = "2020-01-01"
    end_date: str | None = None
    data_dir: str = "data/stocks"
    refresh: bool = False
    data_provider: str = "auto"
    with_benchmark: bool = True
    benchmark: str = "sh000300"
    with_ml: bool = True
    ml_algorithm: str = "both"
    with_openbb_enrichment: bool = True
    max_attempts: int = Field(1, ge=1, le=5)


class ScreenerEnqueueRequest(BaseModel):
    q: str = ""
    has_report: bool | None = None
    stance_in: list[str] = Field(default_factory=list)
    watchlist_only: bool = False
    codes: list[str] = Field(default_factory=list)
    limit: int = Field(20, ge=1, le=50)
    job_type: Literal["qlib_analyze", "analyze_stock"] = "qlib_analyze"
    years: int = Field(2, ge=1, le=10)
    refresh: bool = True
    with_ml: bool = True
    ml_algorithm: str = "both"
    max_attempts: int = Field(2, ge=1, le=5)


class BatchQlibRequest(BaseModel):
    codes: list[str] = Field(..., min_length=1, max_length=50)
    years: int = Field(2, ge=1, le=10)
    refresh: bool = True
    data_dir: str = "data/stocks"
    with_ml: bool = True
    ml_algorithm: str = "both"


class BacktestJobRequest(BaseModel):
    symbols: list[str] | None = None
    start_date: str = "2023-01-01"
    end_date: str | None = None
    lookback: int = 20
    topk: int = 3
    n_drop: int = 1
    initial_cash: float = 1_000_000.0
    benchmark: str = "sh000300"
    signal_mode: str = "momentum"
    ml_algorithm: str = "lgb"
    data_provider: str = "auto"


class MacroJobRequest(BaseModel):
    code: str | None = None
    countries: list[str] = Field(default_factory=lambda: ["china", "united_states"])
    use_fred: bool = True
    fred_start_date: str = "2020-01-01"
    use_fmp_peers: bool = True
    output_dir: str | None = "data/macro"


class CryptoAnalyzeJobRequest(BaseModel):
    symbol: str = "BTC"
    timeframe: str = "5m"
    limit: int = 800
    data_dir: str = "data/crypto"
    with_ml: bool = True
    ml_algorithm: str = "both"


def _store(request: Request):
    store = getattr(request.app.state, "job_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Job store not initialized")
    return store


@router.post("/qlib-analyze", status_code=202)
def enqueue_qlib(req: QlibJobRequest, request: Request) -> dict[str, str]:
    store = _store(request)
    job = store.create(
        type="qlib_analyze",
        code=req.code.strip(),
        payload=req.model_dump(),
    )
    return {"job_id": job["id"]}


@router.post("/analyze-stock", status_code=202)
def enqueue_analyze(req: AnalyzeStockJobRequest, request: Request) -> dict[str, str]:
    store = _store(request)
    job = store.create(
        type="analyze_stock",
        code=req.code.strip(),
        payload=req.model_dump(),
    )
    return {"job_id": job["id"]}


@router.post("/backtest", status_code=202)
def enqueue_backtest(req: BacktestJobRequest, request: Request) -> dict[str, str]:
    store = _store(request)
    syms = req.symbols or ["600519", "000858", "601318"]
    job = store.create(
        type="backtest_run",
        code=",".join(syms),
        payload=req.model_dump(),
    )
    return {"job_id": job["id"]}


@router.post("/macro-panel", status_code=202)
def enqueue_macro(req: MacroJobRequest, request: Request) -> dict[str, str]:
    store = _store(request)
    job = store.create(
        type="macro_panel",
        code=(req.code or "").strip() or None,
        payload=req.model_dump(),
    )
    return {"job_id": job["id"]}


@router.post("/crypto-analyze", status_code=202)
def enqueue_crypto_analyze(req: CryptoAnalyzeJobRequest, request: Request) -> dict[str, str]:
    store = _store(request)
    job = store.create(
        type="crypto_analyze",
        code=req.symbol.strip(),
        payload=req.model_dump(),
    )
    return {"job_id": job["id"]}


@router.post("/screener-enqueue", status_code=202)
def enqueue_screener(req: ScreenerEnqueueRequest, request: Request) -> dict[str, Any]:
    from quant_rd_tool import stock_screener

    store = _store(request)
    screened = stock_screener.run_screener(
        q=req.q,
        has_report=req.has_report,
        stance_in=req.stance_in,
        watchlist_only=req.watchlist_only,
        codes=req.codes,
        page=1,
        page_size=req.limit,
    )
    job_ids: list[str] = []
    for row in screened["items"]:
        code = row["code"]
        if req.job_type == "qlib_analyze":
            payload = {
                "years": req.years,
                "refresh": req.refresh,
                "data_dir": "data/stocks",
                "with_ml": req.with_ml,
                "ml_algorithm": req.ml_algorithm,
                "max_attempts": req.max_attempts,
                "_attempt": 1,
            }
            job = store.create(type="qlib_analyze", code=code, payload=payload)
        else:
            payload = {
                "start_date": "2020-01-01",
                "data_dir": "data/stocks",
                "with_ml": req.with_ml,
                "ml_algorithm": req.ml_algorithm,
                "max_attempts": req.max_attempts,
                "_attempt": 1,
            }
            job = store.create(type="analyze_stock", code=code, payload=payload)
        job_ids.append(job["id"])
    return {"job_ids": job_ids, "matched": screened["total"], "enqueued": len(job_ids)}


@router.post("/batch-qlib", status_code=202)
def enqueue_batch_qlib(req: BatchQlibRequest, request: Request) -> dict[str, Any]:
    store = _store(request)
    child_ids: list[str] = []
    base_payload = req.model_dump(exclude={"codes"})
    for code in req.codes:
        child = store.create(
            type="qlib_analyze",
            code=code.strip(),
            payload=base_payload,
        )
        child_ids.append(child["id"])
    return {"job_ids": child_ids}


@router.get("")
def list_jobs(
    request: Request,
    status: str | None = None,
    type: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    store = _store(request)
    items = store.list_jobs(status=status, type=type, limit=limit)
    return {"items": items}


@router.get("/{job_id}/result")
def get_job_result(job_id: str, request: Request) -> dict[str, Any]:
    import json
    from pathlib import Path

    from quant_rd_tool.job_results import load_job_result

    store = _store(request)
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Job status is {job['status']}")
    rpath = job.get("result_path") or ""
    if not rpath or not Path(rpath).is_file():
        raise HTTPException(status_code=404, detail="No result file")
    try:
        if "data/jobs/results/" in rpath.replace("\\", "/"):
            return load_job_result(rpath)
        if rpath.endswith("report.json"):
            data = json.loads(Path(rpath).read_text(encoding="utf-8"))
            narrative = data.get("narrative") or {}
            return {
                "kind": "stock_report",
                "stance": narrative.get("stance"),
                "summary": narrative.get("summary"),
                "path": rpath,
            }
        return load_job_result(rpath)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{job_id}/events")
async def stream_job_events(job_id: str, request: Request) -> StreamingResponse:
    store = _store(request)
    if not store.get(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    async def generate():
        last_id = 0
        idle_ticks = 0
        while idle_ticks < 120:
            job = store.get(job_id)
            if not job:
                break
            events = store.list_events(job_id, after_id=last_id)
            for ev in events:
                payload = {"type": "event", **ev}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_id = int(ev["id"])
                idle_ticks = 0
            status = job.get("status")
            if status in ("done", "failed", "cancelled"):
                terminal = {
                    "type": "terminal",
                    "status": status,
                    "progress": job.get("progress"),
                    "message": job.get("message"),
                    "error": job.get("error"),
                }
                yield f"data: {json.dumps(terminal, ensure_ascii=False)}\n\n"
                break
            idle_ticks += 1
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{job_id}/retry")
def retry_job(job_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    if not store.get(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if not store.requeue_failed_job(job_id):
        raise HTTPException(status_code=409, detail="Job cannot be retried")
    job = store.get(job_id)
    return job or {}


@router.get("/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    if not store.get(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if not store.mark_cancelled(job_id):
        raise HTTPException(status_code=409, detail="Only queued jobs can be cancelled")
    return store.get(job_id) or {}
