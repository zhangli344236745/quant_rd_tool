from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_rd_tool.openbb_research import build_openbb_research, get_capabilities_report

router = APIRouter()


class OpenBBResearchRequest(BaseModel):
    code: str = Field(..., examples=["600519"])
    use_fred: bool = True
    include_macro: bool = True


@router.get("/capabilities")
def capabilities(probe: bool = True) -> dict[str, Any]:
    """List integrated OpenBB features and credential status."""
    return get_capabilities_report(probe=probe)


@router.post("/research")
def research(req: OpenBBResearchRequest) -> dict[str, Any]:
    """Full OpenBB research bundle for one symbol."""
    try:
        return build_openbb_research(
            req.code,
            include_macro=req.include_macro,
            use_fred=req.use_fred,
        )
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
