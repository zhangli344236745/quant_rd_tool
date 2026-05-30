"""Persist job output snapshots for API / task center."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_RESULTS_DIR = Path("data/jobs/results")


def save_job_result(job_id: str, data: dict[str, Any]) -> str:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _RESULTS_DIR / f"{job_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(path.resolve())


def load_job_result(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    return json.loads(p.read_text(encoding="utf-8"))
