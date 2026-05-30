"""Import and invoke Microsoft RD-Agent Python entrypoints (same as `rdagent fin_*` CLI)."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)


def package_version() -> str | None:
    try:
        return importlib.metadata.version("rdagent")
    except importlib.metadata.PackageNotFoundError:
        return None


def library_status() -> dict[str, Any]:
    """Whether the `rdagent` distribution is installed and core quant modules import."""
    out: dict[str, Any] = {
        "package_version": package_version(),
        "imports_ok": False,
    }
    if out["package_version"] is None:
        out["hint"] = "执行 `uv sync` 安装依赖（含 rdagent 包）。"
        return out
    try:
        import rdagent.app.qlib_rd_loop.factor  # noqa: F401
        import rdagent.app.qlib_rd_loop.factor_from_report  # noqa: F401
        import rdagent.app.qlib_rd_loop.model  # noqa: F401
        import rdagent.app.qlib_rd_loop.quant  # noqa: F401
    except Exception as e:  # noqa: BLE001 — surface import errors to API
        out["import_error"] = repr(e)
        return out
    out["imports_ok"] = True
    return out


def run_rdagent_main(
    command: Literal["fin_quant", "fin_factor", "fin_model", "fin_factor_report"],
    *,
    report_folder: str | None = None,
    session_path: str | None = None,
    step_n: int | None = None,
    loop_n: int | None = None,
    all_duration: str | None = None,
    checkout: bool = True,
) -> None:
    """
    Blocking call into RD-Agent (same functions Typer registers in `rdagent.app.cli`).

    Run only from a worker thread or FastAPI `BackgroundTasks`.
    """
    if command == "fin_quant":
        from rdagent.app.qlib_rd_loop.quant import main

        main(
            path=session_path,
            step_n=step_n,
            loop_n=loop_n,
            all_duration=all_duration,
            checkout=checkout,
        )
    elif command == "fin_factor":
        from rdagent.app.qlib_rd_loop.factor import main

        main(
            path=session_path,
            step_n=step_n,
            loop_n=loop_n,
            all_duration=all_duration,
            checkout=checkout,
        )
    elif command == "fin_model":
        from rdagent.app.qlib_rd_loop.model import main

        main(
            path=session_path,
            step_n=step_n,
            loop_n=loop_n,
            all_duration=all_duration,
            checkout=checkout,
        )
    elif command == "fin_factor_report":
        from rdagent.app.qlib_rd_loop.factor_from_report import main

        main(
            report_folder=report_folder,
            path=session_path,
            all_duration=all_duration,
            checkout=checkout,
        )
    else:
        msg = f"unknown command: {command}"
        raise ValueError(msg)


def run_rdagent_main_logged(**kwargs: Any) -> None:
    """Wrapper for background execution; logs failures instead of crashing the server."""
    try:
        run_rdagent_main(**kwargs)
    except Exception:
        logger.exception("rdagent library run failed: %s", kwargs)
