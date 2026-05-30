from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_rd_tool.backtest_engine import run_backtest
from quant_rd_tool.config import settings
from quant_rd_tool.market_data import DataProvider

router = APIRouter()


class BacktestRequest(BaseModel):
    symbols: list[str] | None = Field(
        default=None,
        description="A股代码列表，如 600519、000858；默认演示组合",
        examples=[["600519", "000858", "601318"]],
    )
    start_date: str = "2023-01-01"
    end_date: str | None = None
    lookback: int = Field(20, ge=5, le=120)
    topk: int = Field(3, ge=1, le=20)
    n_drop: int = Field(1, ge=1, le=10)
    initial_cash: float = Field(1_000_000.0, gt=0)
    benchmark: str = Field("sh000300", description="akshare 指数代码，如 sh000300")
    signal_mode: str = Field("momentum", description="momentum 或 ml")
    ml_algorithm: str = Field("lgb", description="ml 时: xgb | lgb | both(回测用 lgb)")
    data_provider: str = Field(
        "auto",
        description="auto | akshare | openbb",
    )


@router.post("/run")
def run(req: BacktestRequest) -> dict[str, Any]:
    """行情拉数 + qlib 动量/ML Top-K 回测 + 投资建议（研究用途）。"""
    try:
        provider: DataProvider = req.data_provider or settings.data_provider  # type: ignore[assignment]
        return run_backtest(
            req.symbols,
            start_date=req.start_date,
            end_date=req.end_date,
            lookback=req.lookback,
            topk=req.topk,
            n_drop=req.n_drop,
            initial_cash=req.initial_cash,
            benchmark=req.benchmark,
            signal_mode=req.signal_mode,
            ml_algorithm=req.ml_algorithm,  # type: ignore[arg-type]
            data_provider=provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail="未安装 pyqlib 或 Python 版本不兼容（需 3.11–3.12）。",
        ) from e
    except (OSError, ConnectionError) as e:
        raise HTTPException(
            status_code=503,
            detail=f"行情数据获取失败（网络或 akshare 限流）：{e}",
        ) from e
