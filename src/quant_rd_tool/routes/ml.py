from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_rd_tool import akshare_data as ak_data
from quant_rd_tool.qlib_ml import run_ml_analysis
from quant_rd_tool.stock_storage import csv_path, load_csv, qlib_path, stock_root

router = APIRouter()


class MlRequest(BaseModel):
    code: str = Field(..., examples=["600519"])
    start_date: str = "2020-01-01"
    end_date: str | None = None
    data_dir: str = "data/stocks"
    algorithm: str = Field("both", description="xgb | lgb | both")


@router.post("/xgb")
def run_ml(req: MlRequest) -> dict[str, Any]:
    """对已落盘的 qlib 数据运行 Alpha158 + XGBoost 分析。"""
    root = stock_root(req.data_dir, req.code)
    csv_file = csv_path(root)
    if not csv_file.exists():
        raise HTTPException(
            status_code=400,
            detail=f"本地无数据，请先 POST /api/v1/analyze/stock 拉取 {req.code}",
        )
    qlib_dir = qlib_path(root)
    if not qlib_dir.exists():
        raise HTTPException(status_code=400, detail="缺少 qlib 目录，请先运行个股 analyze。")

    df = load_csv(csv_file)
    end = req.end_date
    if end is None:
        end = str(df["date"].max().date())

    try:
        return run_ml_analysis(
            str(qlib_dir.resolve()),
            ak_data.to_qlib_code(req.code),
            start_date=req.start_date,
            end_date=end,
            num_bars=len(df),
            algorithm=req.algorithm,  # type: ignore[arg-type]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"缺少依赖：{e}") from e
