from fastapi import APIRouter

from quant_rd_tool import __version__

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "quant-rd-tool", "version": __version__}
