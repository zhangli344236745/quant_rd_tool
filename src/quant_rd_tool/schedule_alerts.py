"""Schedule job alert rules, cooldown, and webhook delivery."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from quant_rd_tool.network_settings import load_settings

_SETTINGS_PATH = Path("data/settings.json")
_DEFAULT_LOG = Path("data/crypto/schedule_alert_log.jsonl")
_DEFAULT_STATE = Path("data/crypto/alert_state.json")

AlertRuleKind = Literal[
    "cycle_error",
    "worker_crash",
    "consecutive_failures",
    "stale_running",
    "custom_signal",
]


@dataclass
class ScheduleAlertRules:
    enabled: bool = True
    on_cycle_error: bool = True
    on_worker_crash: bool = True
    consecutive_failures: int = 3
    stale_minutes: int = 0
    cooldown_minutes: int = 15

    def __post_init__(self) -> None:
        self.consecutive_failures = max(0, int(self.consecutive_failures))
        self.stale_minutes = max(0, int(self.stale_minutes))
        self.cooldown_minutes = max(1, int(self.cooldown_minutes))


def get_alert_rules() -> dict[str, Any]:
    data = load_settings(_SETTINGS_PATH)
    raw = data.get("schedule_alerts") if isinstance(data.get("schedule_alerts"), dict) else {}
    rules = ScheduleAlertRules(
        enabled=raw.get("enabled", True) is not False,
        on_cycle_error=raw.get("on_cycle_error", True) is not False,
        on_worker_crash=raw.get("on_worker_crash", True) is not False,
        consecutive_failures=int(raw.get("consecutive_failures", 3)),
        stale_minutes=int(raw.get("stale_minutes", 0)),
        cooldown_minutes=int(raw.get("cooldown_minutes", 15)),
    )
    out = asdict(rules)
    out["updated_at"] = raw.get("updated_at")
    custom = raw.get("custom_rules")
    out["custom_rules"] = custom if isinstance(custom, list) else []
    return out


def save_alert_rules(
    *,
    enabled: bool | None = None,
    on_cycle_error: bool | None = None,
    on_worker_crash: bool | None = None,
    consecutive_failures: int | None = None,
    stale_minutes: int | None = None,
    cooldown_minutes: int | None = None,
    custom_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    data = load_settings(_SETTINGS_PATH)
    raw = dict(data.get("schedule_alerts") or {}) if isinstance(data.get("schedule_alerts"), dict) else {}
    if enabled is not None:
        raw["enabled"] = enabled
    if on_cycle_error is not None:
        raw["on_cycle_error"] = on_cycle_error
    if on_worker_crash is not None:
        raw["on_worker_crash"] = on_worker_crash
    if consecutive_failures is not None:
        raw["consecutive_failures"] = consecutive_failures
    if stale_minutes is not None:
        raw["stale_minutes"] = stale_minutes
    if cooldown_minutes is not None:
        raw["cooldown_minutes"] = cooldown_minutes
    if custom_rules is not None:
        from quant_rd_tool.schedule_alert_conditions import validate_custom_rule

        cleaned: list[dict[str, Any]] = []
        for rule in custom_rules:
            if not isinstance(rule, dict):
                continue
            errs = validate_custom_rule(rule)
            if errs:
                raise ValueError(f"custom_rules[{rule.get('id')}]: {', '.join(errs)}")
            cleaned.append(rule)
        raw["custom_rules"] = cleaned
    raw["updated_at"] = datetime.now(UTC).isoformat()
    data["schedule_alerts"] = raw
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_alert_rules()


def _load_state(path: Path = _DEFAULT_STATE) -> dict[str, Any]:
    if not path.is_file():
        return {"jobs": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"jobs": {}}
    except Exception:
        return {"jobs": {}}


def _save_state(state: dict[str, Any], path: Path = _DEFAULT_STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _job_state(state: dict[str, Any], job_id: str) -> dict[str, Any]:
    jobs = state.setdefault("jobs", {})
    if job_id not in jobs or not isinstance(jobs[job_id], dict):
        jobs[job_id] = {"failure_streak": 0, "last_alerts": {}}
    return jobs[job_id]


def append_alert_log(
    entry: dict[str, Any],
    *,
    log_path: Path = _DEFAULT_LOG,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(UTC).isoformat(), **entry}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def tail_alert_log(*, limit: int = 50, log_path: Path = _DEFAULT_LOG) -> list[dict[str, Any]]:
    if not log_path.is_file():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
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


def _cooldown_ok(
    job_st: dict[str, Any],
    rule: str,
    *,
    cooldown_minutes: int,
) -> bool:
    last_alerts = job_st.setdefault("last_alerts", {})
    prev = last_alerts.get(rule)
    if not prev:
        return True
    try:
        prev_dt = datetime.fromisoformat(str(prev).replace("Z", "+00:00"))
        if prev_dt.tzinfo is None:
            prev_dt = prev_dt.replace(tzinfo=UTC)
    except Exception:
        return True
    elapsed = (datetime.now(UTC) - prev_dt).total_seconds() / 60.0
    return elapsed >= cooldown_minutes


def _fire_alert(
    *,
    job_id: str,
    rule: str,
    message: str,
    detail: dict[str, Any] | None = None,
    state_path: Path = _DEFAULT_STATE,
    rules: ScheduleAlertRules | None = None,
) -> bool:
    rules = rules or ScheduleAlertRules(**{k: v for k, v in get_alert_rules().items() if k != "updated_at"})
    if not rules.enabled:
        return False
    state = _load_state(state_path)
    job_st = _job_state(state, job_id)
    if not _cooldown_ok(job_st, rule, cooldown_minutes=rules.cooldown_minutes):
        return False

    entry = {
        "job_id": job_id,
        "rule": rule,
        "message": message,
        "detail": detail or {},
    }
    append_alert_log(entry)
    job_st["last_alerts"][rule] = datetime.now(UTC).isoformat()
    _save_state(state, state_path)

    from quant_rd_tool.crypto_ops_control import get_crypto_ops, post_webhook

    ops = get_crypto_ops()
    url = (ops.get("webhook_url") or "").strip()
    if url and ops.get("webhook_on_error", True):
        try:
            post_webhook(
                url,
                {
                    "kind": "schedule_alert",
                    "decision": rule,
                    "job_id": job_id,
                    "message": message,
                    "detail": detail,
                },
            )
        except Exception:
            pass
    return True


def record_cycle_outcome(
    job_id: str,
    *,
    had_error: bool,
    error_message: str | None = None,
    state_path: Path = _DEFAULT_STATE,
) -> int:
    """Update failure streak; return current streak."""
    state = _load_state(state_path)
    job_st = _job_state(state, job_id)
    if had_error:
        job_st["failure_streak"] = int(job_st.get("failure_streak") or 0) + 1
    else:
        job_st["failure_streak"] = 0
    _save_state(state, state_path)
    return int(job_st["failure_streak"])


def evaluate_after_cycle(
    job_id: str,
    *,
    last_error: str | None,
    last_cycle_summary: list[dict[str, Any]] | None,
    status: str = "running",
    state_path: Path = _DEFAULT_STATE,
) -> list[dict[str, Any]]:
    """Evaluate rules after a schedule cycle completes."""
    raw = get_alert_rules()
    rules = ScheduleAlertRules(**{k: v for k, v in raw.items() if k in ScheduleAlertRules.__dataclass_fields__})
    if not rules.enabled:
        return []

    symbol_errors = [
        s for s in (last_cycle_summary or []) if s.get("error")
    ]
    had_error = bool(last_error) or bool(symbol_errors)
    streak = record_cycle_outcome(job_id, had_error=had_error, state_path=state_path)
    fired: list[dict[str, Any]] = []

    if rules.on_cycle_error and had_error:
        msg = last_error or f"{len(symbol_errors)} symbol(s) failed"
        if _fire_alert(
            job_id=job_id,
            rule="cycle_error",
            message=f"[{job_id}] 调度周期失败: {msg}",
            detail={"last_error": last_error, "symbols": symbol_errors},
            state_path=state_path,
            rules=rules,
        ):
            fired.append({"rule": "cycle_error", "message": msg})

    if (
        rules.consecutive_failures > 0
        and streak >= rules.consecutive_failures
        and had_error
    ):
        msg = f"连续失败 {streak} 次"
        if _fire_alert(
            job_id=job_id,
            rule="consecutive_failures",
            message=f"[{job_id}] {msg}",
            detail={"streak": streak, "last_error": last_error},
            state_path=state_path,
            rules=rules,
        ):
            fired.append({"rule": "consecutive_failures", "message": msg})

    if rules.on_worker_crash and status == "error":
        msg = last_error or "worker crashed"
        if _fire_alert(
            job_id=job_id,
            rule="worker_crash",
            message=f"[{job_id}] 调度线程异常: {msg}",
            detail={"status": status},
            state_path=state_path,
            rules=rules,
        ):
            fired.append({"rule": "worker_crash", "message": msg})

    fired.extend(
        evaluate_custom_rules(
            job_id,
            last_cycle_summary=last_cycle_summary or [],
            state_path=state_path,
            rules=rules,
            raw=raw,
        )
    )

    return fired


def evaluate_custom_rules(
    job_id: str,
    *,
    last_cycle_summary: list[dict[str, Any]],
    state_path: Path = _DEFAULT_STATE,
    rules: ScheduleAlertRules | None = None,
    raw: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from quant_rd_tool.schedule_alert_conditions import (
        format_message,
        rule_matches_cycle,
    )

    raw = raw or get_alert_rules()
    rules = rules or ScheduleAlertRules(
        **{k: v for k, v in raw.items() if k in ScheduleAlertRules.__dataclass_fields__}
    )
    if not rules.enabled:
        return []

    custom_rules = raw.get("custom_rules") or []
    if not isinstance(custom_rules, list):
        return []

    ok_rows = [r for r in last_cycle_summary if not r.get("error")]
    if not ok_rows:
        return []

    fired: list[dict[str, Any]] = []
    for rule in custom_rules:
        if not isinstance(rule, dict):
            continue
        matched, row = rule_matches_cycle(rule, job_id=job_id, cycle_rows=last_cycle_summary)
        if not matched or not row:
            continue
        rule_key = f"custom:{rule.get('id', 'unknown')}"
        msg = format_message(
            str(rule.get("message") or ""),
            job_id=job_id,
            row=row,
            rule=rule,
        )
        if _fire_alert(
            job_id=job_id,
            rule=rule_key,
            message=msg,
            detail={"custom_rule": rule, "symbol_row": row},
            state_path=state_path,
            rules=rules,
        ):
            fired.append({"rule": rule_key, "message": msg, "symbol": row.get("symbol")})
    return fired


def evaluate_stale_jobs(
    jobs: list[dict[str, Any]],
    *,
    state_path: Path = _DEFAULT_STATE,
) -> list[dict[str, Any]]:
    """Alert when a job is 'running' but has not completed a cycle recently."""
    raw = get_alert_rules()
    rules = ScheduleAlertRules(**{k: v for k, v in raw.items() if k in ScheduleAlertRules.__dataclass_fields__})
    if not rules.enabled or rules.stale_minutes <= 0:
        return []

    now = datetime.now(UTC)
    fired: list[dict[str, Any]] = []
    for job in jobs:
        if job.get("status") != "running":
            continue
        job_id = str(job.get("id") or "")
        last_run = job.get("last_run_at")
        if not last_run:
            continue
        try:
            last_dt = datetime.fromisoformat(str(last_run).replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
        except Exception:
            continue
        age_min = (now - last_dt).total_seconds() / 60.0
        if age_min < rules.stale_minutes:
            continue
        msg = f"超过 {int(age_min)} 分钟未成功跑完周期（阈值 {rules.stale_minutes}m）"
        if _fire_alert(
            job_id=job_id,
            rule="stale_running",
            message=f"[{job_id}] 调度可能卡住: {msg}",
            detail={"last_run_at": last_run, "age_minutes": round(age_min, 1)},
            state_path=state_path,
            rules=rules,
        ):
            fired.append({"job_id": job_id, "rule": "stale_running", "message": msg})
    return fired
