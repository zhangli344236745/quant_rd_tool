from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from quant_rd_tool.rdagent_bridge import (
    RDCommand,
    dispatch_rdagent_cli,
    platform_note,
    rdagent_executable,
)
from quant_rd_tool.rdagent_library import library_status, run_rdagent_main_logged

router = APIRouter()


class DispatchBody(BaseModel):
    command: RDCommand
    mode: Literal["library", "subprocess"] = "library"
    extra_args: list[str] = Field(default_factory=list)
    detach: bool = True
    session_path: str | None = Field(
        default=None,
        description="恢复会话时的状态路径（对应 RD-Agent 文档中的 path）",
    )
    report_folder: str | None = Field(
        default=None,
        description="fin_factor_report 时必填：财报 PDF 所在目录",
    )
    step_n: int | None = None
    loop_n: int | None = None
    all_duration: str | None = None
    checkout: bool = True


@router.get("/status")
def status() -> dict[str, Any]:
    return {
        "rdagent_on_path": rdagent_executable(),
        "library": library_status(),
        "platform": platform_note(),
    }


@router.post("/dispatch")
def dispatch(body: DispatchBody, background_tasks: BackgroundTasks) -> dict[str, Any]:
    if body.command == RDCommand.fin_factor_report and not body.report_folder:
        raise HTTPException(
            status_code=400,
            detail="fin_factor_report 需要提供 report_folder。",
        )

    if body.mode == "library":
        lib = library_status()
        if not lib.get("imports_ok"):
            detail = lib.get("import_error") or lib.get("hint") or "rdagent 未正确安装或导入失败"
            raise HTTPException(status_code=503, detail=detail)

        kwargs: dict[str, Any] = {
            "command": body.command.value,
            "report_folder": body.report_folder,
            "session_path": body.session_path,
            "step_n": body.step_n,
            "loop_n": body.loop_n,
            "all_duration": body.all_duration,
            "checkout": body.checkout,
        }
        background_tasks.add_task(run_rdagent_main_logged, **kwargs)
        return {
            "ok": True,
            "mode": "library",
            "command": body.command.value,
            "message": (
                "已在服务器进程内通过 rdagent 包调用对应 main()（BackgroundTasks，"
                "与 CLI `rdagent "
                + body.command.value
                + "` 同源）。查看 RD-Agent 日志与输出目录。"
            ),
        }

    res = dispatch_rdagent_cli(body.command, extra_args=body.extra_args, detach=body.detach)
    if not res.ok and not res.pid:
        raise HTTPException(status_code=503, detail=res.message)
    return {
        "ok": res.ok,
        "mode": "subprocess",
        "command": res.command,
        "message": res.message,
        "pid": res.pid,
    }
