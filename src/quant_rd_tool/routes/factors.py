from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from yfinance.exceptions import YFRateLimitError

from quant_rd_tool import factors as fac

router = APIRouter()


class FactorRequest(BaseModel):
    symbol: str = Field(..., examples=["AAPL", "600519.SS"])
    period: str = "1y"
    interval: str = "1d"


@router.post("/compute")
def compute(req: FactorRequest) -> dict[str, Any]:
    try:
        df = fac.fetch_ohlcv(req.symbol, period=req.period, interval=req.interval)
        snapshot = fac.compute_factors(df)
    except YFRateLimitError as e:
        raise HTTPException(
            status_code=503,
            detail="Yahoo Finance 限流，请稍后再试或更换网络环境。",
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"symbol": req.symbol, **snapshot}
