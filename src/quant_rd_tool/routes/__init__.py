from fastapi import APIRouter

from quant_rd_tool.routes import (
    analyze,
    backtest,
    crypto,
    enterprise,
    factors,
    jobs,
    macro,
    meta,
    ml,
    openbb,
    rdagent_ops,
    research,
    settings_routes,
    stocks,
)

api_router = APIRouter()
api_router.include_router(meta.router, tags=["meta"])
api_router.include_router(enterprise.router, prefix="/enterprise", tags=["enterprise"])
api_router.include_router(factors.router, prefix="/factors", tags=["factors"])
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(backtest.router, prefix="/backtest", tags=["backtest"])
api_router.include_router(analyze.router, prefix="/analyze", tags=["analyze"])
api_router.include_router(ml.router, prefix="/ml", tags=["ml"])
api_router.include_router(macro.router, prefix="/macro", tags=["macro"])
api_router.include_router(openbb.router, prefix="/openbb", tags=["openbb"])
api_router.include_router(crypto.router, prefix="/crypto", tags=["crypto"])
api_router.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(settings_routes.router, prefix="/settings", tags=["settings"])
api_router.include_router(rdagent_ops.router, prefix="/rdagent", tags=["rdagent"])
