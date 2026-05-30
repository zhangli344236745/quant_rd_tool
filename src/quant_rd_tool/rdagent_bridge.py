"""Spawn Microsoft RD-Agent CLI when available (Linux / full install)."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from subprocess import PIPE, Popen
from typing import Any


class RDCommand(StrEnum):
    fin_quant = "fin_quant"
    fin_factor = "fin_factor"
    fin_model = "fin_model"
    fin_factor_report = "fin_factor_report"


@dataclass
class DispatchResult:
    ok: bool
    command: list[str]
    message: str
    pid: int | None = None


def rdagent_executable() -> str | None:
    return shutil.which("rdagent")


def dispatch_rdagent_cli(
    cmd: RDCommand,
    *,
    extra_args: list[str] | None = None,
    detach: bool = True,
) -> DispatchResult:
    exe = rdagent_executable()
    if not exe:
        return DispatchResult(
            ok=False,
            command=[],
            message="未在 PATH 中找到 `rdagent`。请执行 `uv sync` 并确认虚拟环境已激活。",
        )

    argv = [exe, cmd.value, *(extra_args or [])]
    if detach:
        proc = Popen(argv, stdout=PIPE, stderr=PIPE, stdin=PIPE)  # noqa: S603
        return DispatchResult(
            ok=True,
            command=argv,
            message="已在后台启动 RD-Agent 子进程（日志请查看终端或 RD-Agent 配置的工作目录）。",
            pid=proc.pid,
        )

    proc = Popen(argv, stdout=PIPE, stderr=PIPE)  # noqa: S603
    out, err = proc.communicate()
    ok = proc.returncode == 0
    return DispatchResult(
        ok=ok,
        command=argv,
        message=(out or b"").decode()[-4000:] + (err or b"").decode()[-2000:],
        pid=None,
    )


def platform_note() -> dict[str, Any]:
    return {
        "python_platform": sys.platform,
        "upstream_note": (
            "Microsoft RD-Agent 官方文档声明当前主要支持 Linux；"
            "Docker 与 Qlib 等依赖在 macOS 上可能受限。"
        ),
        "docs": "https://rdagent.readthedocs.io/en/latest/scens/quant_agent_fin.html",
    }
