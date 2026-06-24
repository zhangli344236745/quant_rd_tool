from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quant_rd_tool.enterprise.middleware import EnterpriseMiddleware
from quant_rd_tool.frontend_static import mount_frontend
from quant_rd_tool.job_runner import JobRunner
from quant_rd_tool.job_store import JobStore
from quant_rd_tool.network_settings import apply_network_env
from quant_rd_tool.routes import api_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = JobStore(Path("data/jobs/jobs.db"))
    recovered = store.recover_stale_running()
    if recovered:
        import logging

        logging.getLogger(__name__).warning("Recovered %d stale running jobs", recovered)
    runner = JobRunner(store)
    apply_network_env()
    runner.start_background()
    app.state.job_store = store
    app.state.job_runner = runner
    try:
        from quant_rd_tool.stock_vbt_scheduler import boot_vbt_scheduler_if_enabled

        boot_vbt_scheduler_if_enabled()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("VBT scheduler boot failed")
    try:
        from quant_rd_tool.crypto_polymarket_runner import boot_polymarket_scheduler_if_enabled

        boot_polymarket_scheduler_if_enabled()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Polymarket scheduler boot failed")
    yield
    try:
        from quant_rd_tool.crypto_polymarket_runner import get_polymarket_runner

        get_polymarket_runner().stop()
    except Exception:
        pass
    try:
        from quant_rd_tool.stock_vbt_scheduler import get_vbt_scheduler

        get_vbt_scheduler().stop()
    except Exception:
        pass
    runner.stop()


app = FastAPI(
    title="quant-rd-tool",
    description="股票因子 + 投资研报 API，可选调度 Microsoft RD-Agent CLI。",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(EnterpriseMiddleware)
app.include_router(api_router, prefix="/api/v1")

_FRONTEND_MOUNTED = mount_frontend(app)


if not _FRONTEND_MOUNTED:

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "docs": "/docs",
            "health": "/api/v1/health",
            "console_hint": "cd src/quant_trade_tool && npm run build",
        }
