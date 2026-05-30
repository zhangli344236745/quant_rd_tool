from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_rd_tool.config import settings
from quant_rd_tool.market_data import DataProvider
from quant_rd_tool.stock_analysis import analyze_stock

router = APIRouter()


class AnalyzeRequest(BaseModel):
    code: str = Field(..., description="股票代码，如 600519 或 SH600519", examples=["600519"])
    start_date: str = "2020-01-01"
    end_date: str | None = None
    data_dir: str = "data/stocks"
    refresh: bool = Field(False, description="True 时强制重新拉取行情")
    data_provider: str = Field(
        "auto",
        description="auto | akshare | openbb（默认读 QUANT_RD_DATA_PROVIDER）",
    )
    with_benchmark: bool = True
    benchmark: str = "sh000300"
    with_ml: bool = Field(True, description="是否运行 qlib Alpha158 ML 分析")
    ml_algorithm: str = Field("both", description="xgb | lgb | both")
    with_openbb_enrichment: bool = Field(True, description="是否附加 OpenBB 新闻/概况")


@router.post("/stock")
def analyze(req: AnalyzeRequest) -> dict[str, Any]:
    """拉取/加载本地数据 → qlib 格式 → 个股分析报告。"""
    try:
        provider: DataProvider = req.data_provider or settings.data_provider  # type: ignore[assignment]
        return analyze_stock(
            req.code,
            start_date=req.start_date,
            end_date=req.end_date,
            data_dir=req.data_dir,
            refresh=req.refresh,
            with_benchmark=req.with_benchmark,
            benchmark=req.benchmark,
            with_ml=req.with_ml,
            ml_algorithm=req.ml_algorithm,  # type: ignore[arg-type]
            data_provider=provider,
            with_openbb_enrichment=req.with_openbb_enrichment,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (OSError, ConnectionError) as e:
        raise HTTPException(status_code=503, detail=f"行情获取失败：{e}") from e
