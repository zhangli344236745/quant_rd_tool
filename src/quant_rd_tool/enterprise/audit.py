"""Append-only API audit log."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_AUDIT_PATH = Path("data/enterprise/audit.jsonl")


def append_audit(entry: dict[str, Any], *, path: Path = _AUDIT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": now_iso(), **entry}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def tail_audit(
    *,
    limit: int = 100,
    path: str | Path = _AUDIT_PATH,
    principal: str | None = None,
) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        if len(rows) >= limit:
            break
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if principal and row.get("principal") != principal:
            continue
        rows.append(row)
    rows.reverse()
    return rows
