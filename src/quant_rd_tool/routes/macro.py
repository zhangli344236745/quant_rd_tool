from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_rd_tool.macro_panel import build_macro_panel, save_macro_panel

router = APIRouter()


class MacroPanelRequest(BaseModel):
    code: str | None = Field(None, description="可选股票代码，附带行业/同业")
    countries: list[str] = Field(
        default_factory=lambda: ["china", "united_states"],
        description="econdb country_profile 国家列表",
    )
    use_fred: bool = True
    fred_start_date: str = "2020-01-01"
    use_fmp_peers: bool = True
    output_dir: str | None = Field(None, description="若设置则写入 panel.json / panel.md")


@router.post("/panel")
def macro_panel(req: MacroPanelRequest) -> dict[str, Any]:
    """拉取 OpenBB 宏观/行业面板（可落盘）。"""
    try:
        panel = build_macro_panel(
            code=req.code,
            countries=tuple(req.countries),
            use_fred=req.use_fred,
            fred_start_date=req.fred_start_date,
            use_fmp_peers=req.use_fmp_peers,
        )
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except (OSError, ConnectionError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    result: dict[str, Any] = {k: v for k, v in panel.items() if k != "markdown"}
    result["markdown"] = panel["markdown"]
    if req.output_dir:
        result["saved"] = save_macro_panel(panel, req.output_dir)
    return result
