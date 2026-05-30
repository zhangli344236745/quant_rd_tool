"""Read-only helpers for crypto trading ops dashboard (telemetry, perp state, schedules)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from quant_rd_tool.perp_state import PerpSymbolState
from quant_rd_tool.perp_telemetry import daily_log_path


def tail_jsonl(
    log_dir: str | Path,
    *,
    day: date | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return last ``limit`` JSON objects from the daily log (newest last)."""
    path = daily_log_path(log_dir, day=day)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) :]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def summarize_telemetry(events: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = Counter(str(e.get("decision") or "unknown") for e in events)
    errors = [e for e in events if e.get("error_category")]
    blocked = sum(1 for e in events if e.get("decision") == "blocked_circuit_breaker")
    return {
        "total": len(events),
        "decisions": dict(decisions),
        "error_count": len(errors),
        "circuit_breaker_blocks": blocked,
        "last_ts": events[-1].get("ts") if events else None,
    }


def list_perp_states(data_dir: str | Path = "data/crypto") -> list[dict[str, Any]]:
    base = Path(data_dir).expanduser()
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(base.glob("perp_state_*.json")):
        sym = path.stem.replace("perp_state_", "")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        prot_path = base / f"perp_protection_{sym}.json"
        prot: dict[str, Any] = {}
        if prot_path.is_file():
            try:
                ps = PerpSymbolState.load(prot_path)
                prot = {
                    "protection_fail_streak": ps.protection_fail_streak,
                    "soft_protection_active": ps.soft_protection_active,
                    "daily_date": ps.daily_date,
                    "daily_start_usdt_total": ps.daily_start_usdt_total,
                    "sl_status": ps.sl_order.status,
                    "tp_status": ps.tp_order.status,
                }
            except Exception:
                prot = {"error": "failed to parse protection state"}
        out.append(
            {
                "base": sym,
                "state_path": str(path),
                "last_seen_bar_end": raw.get("last_seen_bar_end"),
                "last_target_side": raw.get("last_target_side"),
                "position": raw.get("position"),
                "protection": prot,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )
    return out


def list_telemetry_days(log_dir: str | Path) -> list[str]:
    d = Path(log_dir).expanduser()
    if not d.is_dir():
        return []
    days = sorted(
        {p.stem for p in d.glob("*.jsonl") if len(p.stem) == 8 and p.stem.isdigit()},
        reverse=True,
    )
    return days


def build_ops_summary(
    *,
    data_dir: str = "data/crypto",
    log_dir: str = "data/crypto/perp_logs",
    telemetry_limit: int = 80,
) -> dict[str, Any]:
    from quant_rd_tool.scheduler_manager import get_scheduler_manager

    mgr = get_scheduler_manager(data_dir)
    jobs = mgr.list_jobs()
    running = sum(1 for j in jobs if j.get("status") == "running")
    events = tail_jsonl(log_dir, limit=telemetry_limit)
    from quant_rd_tool.crypto_ops_control import get_crypto_ops
    from quant_rd_tool.schedule_alerts import evaluate_stale_jobs, get_alert_rules, tail_alert_log

    stale_fired = evaluate_stale_jobs(jobs)
    return {
        "data_dir": data_dir,
        "log_dir": log_dir,
        "control": get_crypto_ops(),
        "schedules": {
            "total": len(jobs),
            "running": running,
            "jobs": jobs,
        },
        "perp_states": list_perp_states(data_dir),
        "telemetry_days": list_telemetry_days(log_dir),
        "telemetry_summary": summarize_telemetry(events),
        "telemetry_recent": events[-30:],
        "schedule_alerts": get_alert_rules(),
        "schedule_alert_recent": tail_alert_log(limit=20),
        "schedule_stale_checks": stale_fired,
    }
