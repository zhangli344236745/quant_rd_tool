"""JSONL history for portfolio-level Greeks snapshots."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def greeks_history_dir(data_dir: str | Path = "data/crypto") -> Path:
    return Path(data_dir) / "options_portfolio_greeks"


def portfolio_id_from_bases(bases: list[str]) -> str:
    clean = sorted({b.strip().upper() for b in bases if b and str(b).strip()})
    if len(clean) == 1:
        return clean[0]
    return "multi:" + ",".join(clean)


def greeks_history_path(portfolio_id: str, data_dir: str | Path = "data/crypto") -> Path:
    safe = portfolio_id.replace("/", "_").replace(":", "_")
    return greeks_history_dir(data_dir) / f"{safe}.jsonl"


def snapshot_from_report(report: dict[str, Any]) -> dict[str, Any] | None:
    if not report.get("available"):
        return None
    summary = report.get("summary") or {}
    alloc = report.get("allocation") or {}
    bases = report.get("bases")
    if not bases:
        b = report.get("base")
        bases = [b] if b else []
    pid = report.get("portfolio_id") or portfolio_id_from_bases(list(bases))
    row: dict[str, Any] = {
        "ts": now_iso(),
        "portfolio_id": pid,
        "bases": bases,
        "scale_mode": report.get("scale_mode", "notional"),
        "capital": alloc.get("capital"),
        "margin_used_usd": summary.get("margin_used_usd"),
        "delta_usd": summary.get("delta_usd"),
        "net": summary.get("net"),
        "risk_level": summary.get("risk_level"),
    }
    if report.get("multi"):
        row["constituents"] = [
            {
                "base": c.get("base"),
                "weight_pct": c.get("weight_pct"),
                "delta_usd": (c.get("summary") or {}).get("delta_usd"),
            }
            for c in report.get("constituents") or []
        ]
    return row


def append_greeks_snapshot(row: dict[str, Any], *, data_dir: str | Path = "data/crypto") -> Path:
    pid = str(row.get("portfolio_id") or "UNKNOWN")
    path = greeks_history_path(pid, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def persist_portfolio_greeks_report(
    report: dict[str, Any],
    *,
    data_dir: str | Path = "data/crypto",
) -> Path | None:
    row = snapshot_from_report(report)
    if not row:
        return None
    return append_greeks_snapshot(row, data_dir=data_dir)


def load_greeks_history(
    portfolio_id: str,
    *,
    data_dir: str | Path = "data/crypto",
    limit: int = 200,
) -> list[dict[str, Any]]:
    path = greeks_history_path(portfolio_id, data_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
