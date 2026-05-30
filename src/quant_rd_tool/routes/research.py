from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from yfinance.exceptions import YFRateLimitError

from quant_rd_tool import factors as fac
from quant_rd_tool.research import build_research_memo

router = APIRouter()


class MemoRequest(BaseModel):
    symbol: str = Field(..., examples=["MSFT"])
    thesis: str = Field(
        ...,
        description="投资关注点或命题，例如：AI 资本开支周期下的云业务弹性。",
    )
    period: str = "1y"
    interval: str = "1d"


@router.post("/memo")
async def memo(req: MemoRequest) -> dict[str, Any]:
    try:
        df = fac.fetch_ohlcv(req.symbol, period=req.period, interval=req.interval)
        snap = fac.compute_factors(df)
    except YFRateLimitError as e:
        raise HTTPException(
            status_code=503,
            detail="Yahoo Finance 限流，请稍后再试或更换网络环境。",
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await build_research_memo(symbol=req.symbol, thesis=req.thesis, factor_snapshot=snap)
