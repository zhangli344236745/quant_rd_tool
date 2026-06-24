"""Schedule job alert rules, cooldown, and webhook delivery."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from quant_rd_tool.network_settings import load_settings, settings_json_path

logger = logging.getLogger(__name__)
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
    data = load_settings(settings_json_path())
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
    var = raw.get("var")
    out["var"] = var if isinstance(var, dict) else {}
    out["webhook_on_alert"] = raw.get("webhook_on_alert", True) is not False
    out["on_cycle_complete"] = raw.get("on_cycle_complete", True) is not False
    out["on_stance_changed"] = raw.get("on_stance_changed", True) is not False
    bark = raw.get("bark")
    out["bark"] = _public_bark_config(bark if isinstance(bark, dict) else {})
    crypto_news = raw.get("crypto_news")
    out["crypto_news"] = crypto_news if isinstance(crypto_news, dict) else _default_crypto_news_alert_config()
    stock_ann = raw.get("stock_announcements")
    out["stock_announcements"] = (
        stock_ann if isinstance(stock_ann, dict) else _default_stock_announcements_alert_config()
    )
    return out


def _default_stock_announcements_alert_config() -> dict[str, Any]:
    return {
        "on_high_impact": True,
        "min_score": 70,
    }


def get_stock_announcements_alert_config(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw or get_alert_rules()
    section = raw.get("stock_announcements")
    cfg = _default_stock_announcements_alert_config()
    if isinstance(section, dict):
        cfg.update({k: section[k] for k in cfg if k in section and section[k] is not None})
    cfg["on_high_impact"] = cfg.get("on_high_impact", True) is not False
    cfg["min_score"] = int(cfg.get("min_score", 70))
    return cfg


def _default_crypto_news_alert_config() -> dict[str, Any]:
    return {
        "on_high_impact": True,
        "min_score": 70,
        "min_llm_confidence": 0.8,
    }


def get_crypto_news_alert_config(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw or get_alert_rules()
    section = raw.get("crypto_news")
    cfg = _default_crypto_news_alert_config()
    if isinstance(section, dict):
        cfg.update({k: section[k] for k in cfg if k in section})
    cfg["on_high_impact"] = cfg.get("on_high_impact", True) is not False
    cfg["min_score"] = int(cfg.get("min_score", 70))
    cfg["min_llm_confidence"] = float(cfg.get("min_llm_confidence", 0.8))
    return cfg


def _format_cycle_complete_message(job_id: str, rows: list[dict[str, Any]]) -> str:
    from quant_rd_tool.notification_format import format_cycle_complete_body, rule_meta

    meta = rule_meta("cycle_complete")
    header = f"{meta['emoji']} {meta['label']} · {job_id}"
    return f"{header}\n{format_cycle_complete_body(job_id, rows)}"


def _bark_from_env() -> dict[str, str]:
    from quant_rd_tool.config import settings

    return {
        "device_key": str(settings.bark_device_key or "").strip(),
        "server": str(settings.bark_server or "").strip(),
    }


def _coerce_bool(val: Any, *, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return default


def _normalize_bark_config(bark: dict[str, Any]) -> dict[str, Any]:
    from quant_rd_tool.bark_push import DEFAULT_BARK_SERVER

    env = _bark_from_env()
    file_key = str(bark.get("device_key") or "").strip()
    device_key = file_key or env["device_key"]
    server = (
        str(bark.get("server") or "").strip()
        or env["server"]
        or DEFAULT_BARK_SERVER
    ).rstrip("/") or DEFAULT_BARK_SERVER
    return {
        "enabled": _coerce_bool(bark.get("enabled"), default=False),
        "device_key": device_key,
        "server": server,
        "device_key_from_env": bool(env["device_key"] and not file_key),
    }


def _public_bark_config(bark: dict[str, Any]) -> dict[str, Any]:
    """API/UI view: never echo device_key when it comes from .env."""
    cfg = _normalize_bark_config(bark)
    out = dict(cfg)
    out["device_key_configured"] = bool(cfg["device_key"])
    if cfg.get("device_key_from_env"):
        out["device_key"] = ""
    return out


def _bark_config_for_storage(bark: dict[str, Any]) -> dict[str, Any]:
    """Persist schedule_alerts.bark without duplicating secrets already in .env."""
    cfg = _normalize_bark_config(bark)
    env = _bark_from_env()
    stored: dict[str, Any] = {
        "enabled": cfg["enabled"],
        "server": cfg["server"],
    }
    file_key = str(bark.get("device_key") or "").strip()
    if file_key and file_key != env["device_key"]:
        stored["device_key"] = file_key
    return stored


def save_alert_rules(
    *,
    enabled: bool | None = None,
    on_cycle_error: bool | None = None,
    on_worker_crash: bool | None = None,
    consecutive_failures: int | None = None,
    stale_minutes: int | None = None,
    cooldown_minutes: int | None = None,
    custom_rules: list[dict[str, Any]] | None = None,
    var: dict[str, Any] | None = None,
    bark: dict[str, Any] | None = None,
    webhook_on_alert: bool | None = None,
    on_cycle_complete: bool | None = None,
    on_stance_changed: bool | None = None,
    crypto_news: dict[str, Any] | None = None,
    stock_announcements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = load_settings(settings_json_path())
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
    if var is not None:
        if not isinstance(var, dict):
            raise ValueError("var must be an object")
        raw["var"] = var
    if bark is not None:
        if not isinstance(bark, dict):
            raise ValueError("bark must be an object")
        normalized = _normalize_bark_config(bark)
        if normalized["enabled"] and not normalized["device_key"]:
            raise ValueError(
                "bark.device_key is required when bark.enabled is true "
                "(set in UI or BARK_DEVICE_KEY in .env)"
            )
        raw["bark"] = _bark_config_for_storage(bark)
    if webhook_on_alert is not None:
        raw["webhook_on_alert"] = webhook_on_alert
    if on_cycle_complete is not None:
        raw["on_cycle_complete"] = on_cycle_complete
    if on_stance_changed is not None:
        raw["on_stance_changed"] = on_stance_changed
    if crypto_news is not None:
        if not isinstance(crypto_news, dict):
            raise ValueError("crypto_news must be an object")
        ent = dict(raw.get("crypto_news") or {}) if isinstance(raw.get("crypto_news"), dict) else {}
        for k in ("on_high_impact", "min_score", "min_llm_confidence"):
            if k in crypto_news and crypto_news[k] is not None:
                ent[k] = crypto_news[k]
        raw["crypto_news"] = ent
    if stock_announcements is not None:
        if not isinstance(stock_announcements, dict):
            raise ValueError("stock_announcements must be an object")
        ent = dict(raw.get("stock_announcements") or {}) if isinstance(raw.get("stock_announcements"), dict) else {}
        for k in ("on_high_impact", "min_score"):
            if k in stock_announcements and stock_announcements[k] is not None:
                ent[k] = stock_announcements[k]
        raw["stock_announcements"] = ent
    raw["updated_at"] = now_iso()
    data["schedule_alerts"] = raw
    path = settings_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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


def evaluate_stance_changes(
    job_id: str,
    *,
    last_cycle_summary: list[dict[str, Any]],
    state_path: Path = _DEFAULT_STATE,
    rules: ScheduleAlertRules | None = None,
    raw: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fire when a symbol stance changes vs previous successful cycle."""
    raw = raw or get_alert_rules()
    if raw.get("on_stance_changed", True) is False:
        return []
    rules = rules or ScheduleAlertRules(
        **{k: v for k, v in raw.items() if k in ScheduleAlertRules.__dataclass_fields__}
    )
    if not rules.enabled:
        return []

    state = _load_state(state_path)
    job_st = _job_state(state, job_id)
    prev = job_st.setdefault("last_stances", {})
    if not isinstance(prev, dict):
        prev = {}
        job_st["last_stances"] = prev

    fired: list[dict[str, Any]] = []
    for row in last_cycle_summary:
        if row.get("error"):
            continue
        sym = str(row.get("symbol") or row.get("code") or "").strip()
        stance = row.get("stance")
        if not sym or not stance:
            continue
        old = prev.get(sym)
        prev[sym] = stance
        if old and old != stance:
            msg = f"{sym}: {old} → {stance}"
            if _fire_alert(
                job_id=job_id,
                rule="stance_changed",
                message=f"[{job_id}] 立场变化 {msg}",
                detail={"symbol": sym, "from": old, "to": stance},
                state_path=state_path,
                rules=rules,
            ):
                fired.append({"rule": "stance_changed", "message": msg})

    _save_state(state, state_path)
    return fired


def append_alert_log(
    entry: dict[str, Any],
    *,
    log_path: Path = _DEFAULT_LOG,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": now_iso(), **entry}
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
    from quant_rd_tool.notification_format import alert_feed_item

    return [alert_feed_item(row) for row in rows]


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
    job_st["last_alerts"][rule] = now_iso()
    _save_state(state, state_path)

    _deliver_schedule_notifications(
        job_id=job_id,
        rule=rule,
        message=message,
        detail=detail or {},
    )
    return True


def _deliver_schedule_notifications(
    *,
    job_id: str,
    rule: str,
    message: str,
    detail: dict[str, Any],
) -> None:
    """Push schedule alerts via optional Webhook (Crypto 运营 URL) and/or Bark."""
    raw = get_alert_rules()

    if raw.get("webhook_on_alert", True):
        from quant_rd_tool.crypto_ops_control import get_crypto_ops, post_webhook

        ops = get_crypto_ops()
        url = (ops.get("webhook_url") or "").strip()
        if url:
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
                logger.debug("Schedule webhook failed for %s", job_id, exc_info=True)

    bark_cfg = _normalize_bark_config(
        raw.get("bark") if isinstance(raw.get("bark"), dict) else {}
    )
    if bark_cfg["enabled"] and bark_cfg["device_key"]:
        try:
            from quant_rd_tool.bark_push import post_bark
            from quant_rd_tool.notification_format import format_schedule_alert_bark

            bark = format_schedule_alert_bark(
                job_id=job_id, rule=rule, message=message, detail=detail
            )
            post_bark(
                bark_cfg["device_key"],
                title=bark["title"],
                body=bark["body"],
                subtitle=bark.get("subtitle"),
                level=bark.get("level"),
                server=bark_cfg["server"],
                group=bark.get("group", "schedule"),
            )
        except Exception:
            logger.warning("Bark push failed for %s", job_id, exc_info=True)


def send_test_bark(bark: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a test Bark; merges request body with ``BARK_DEVICE_KEY`` from .env."""
    bark_cfg = _normalize_bark_config(bark if isinstance(bark, dict) else {})
    if not bark_cfg["device_key"]:
        raise ValueError("请在 .env 设置 BARK_DEVICE_KEY，或在页面填写 Device Key")

    from quant_rd_tool.bark_push import post_bark
    from quant_rd_tool.notification_format import format_test_bark

    bark = format_test_bark()
    return post_bark(
        bark_cfg["device_key"],
        title=bark["title"],
        body=bark["body"],
        subtitle=bark.get("subtitle"),
        level=bark.get("level"),
        server=bark_cfg["server"],
        group=bark.get("group", "schedule"),
    )


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

    if raw.get("on_cycle_complete", True) and not had_error:
        ok_rows = [r for r in (last_cycle_summary or []) if not r.get("error")]
        if ok_rows:
            msg = _format_cycle_complete_message(job_id, ok_rows)
            bark_cfg = _normalize_bark_config(
                raw.get("bark") if isinstance(raw.get("bark"), dict) else {}
            )
            if bark_cfg["enabled"] and bark_cfg["device_key"]:
                if _fire_alert(
                    job_id=job_id,
                    rule="cycle_complete",
                    message=msg,
                    detail={"symbols": ok_rows},
                    state_path=state_path,
                    rules=rules,
                ):
                    fired.append({"rule": "cycle_complete", "message": msg})

    fired.extend(
        evaluate_custom_rules(
            job_id,
            last_cycle_summary=last_cycle_summary or [],
            state_path=state_path,
            rules=rules,
            raw=raw,
        )
    )
    fired.extend(
        evaluate_var_breaches(
            job_id,
            last_cycle_summary=last_cycle_summary or [],
            state_path=state_path,
            rules=rules,
            raw=raw,
        )
    )
    fired.extend(
        evaluate_stance_changes(
            job_id,
            last_cycle_summary=last_cycle_summary or [],
            state_path=state_path,
            rules=rules,
            raw=raw,
        )
    )

    return fired


def evaluate_news_alerts(
    job_id: str,
    digest: dict[str, Any],
    *,
    state_path: Path = _DEFAULT_STATE,
) -> list[dict[str, Any]]:
    """Alert when digest top items exceed high-impact score/confidence thresholds."""
    raw = get_alert_rules()
    rules = ScheduleAlertRules(
        **{k: v for k, v in raw.items() if k in ScheduleAlertRules.__dataclass_fields__}
    )
    if not rules.enabled:
        return []

    cfg = get_crypto_news_alert_config(raw)
    if not cfg.get("on_high_impact", True):
        return []

    min_score = int(cfg.get("min_score", 70))
    min_conf = float(cfg.get("min_llm_confidence", 0.8))
    fired: list[dict[str, Any]] = []

    for item in digest.get("top_items") or []:
        if not isinstance(item, dict):
            continue
        score = item.get("score")
        advice = item.get("advice") if isinstance(item.get("advice"), dict) else {}
        confidence = advice.get("confidence")
        try:
            if score is None or int(score) < min_score:
                continue
        except (TypeError, ValueError):
            continue
        try:
            if confidence is None or float(confidence) < min_conf:
                continue
        except (TypeError, ValueError):
            continue

        title = str(item.get("title") or advice.get("headline") or "News item")
        impact = advice.get("impact") or item.get("impact_direction") or "neutral"
        msg = (
            f"[{job_id}] 高影响舆论: {title}\n"
            f"分数 {score} | 置信 {float(confidence):.0%} | 方向 {impact}"
        )
        if _fire_alert(
            job_id=job_id,
            rule="news_high_impact",
            message=msg,
            detail={"item": item, "digest_generated_at": digest.get("generated_at")},
            state_path=state_path,
            rules=rules,
        ):
            fired.append({"rule": "news_high_impact", "message": msg, "title": title})

    return fired


def evaluate_announcement_alerts(
    job_id: str,
    digest: dict[str, Any],
    *,
    state_path: Path = _DEFAULT_STATE,
) -> list[dict[str, Any]]:
    """Alert when announcement digest top items exceed score threshold."""
    raw = get_alert_rules()
    rules = ScheduleAlertRules(
        **{k: v for k, v in raw.items() if k in ScheduleAlertRules.__dataclass_fields__}
    )
    if not rules.enabled:
        return []

    cfg = get_stock_announcements_alert_config(raw)
    if not cfg.get("on_high_impact", True):
        return []

    min_score = int(cfg.get("min_score", 70))
    fired: list[dict[str, Any]] = []

    for item in digest.get("top_items") or []:
        if not isinstance(item, dict):
            continue
        score = item.get("score")
        try:
            if score is None or int(score) < min_score:
                continue
        except (TypeError, ValueError):
            continue

        code = str(item.get("code") or "")
        title = str(item.get("title") or "公告")
        keywords = item.get("keywords") or []
        kw_text = "、".join(str(k) for k in keywords[:3]) if keywords else "—"
        msg = (
            f"[{job_id}] 高影响公告: {code} {title}\n"
            f"分数 {score} | 关键词 {kw_text}"
        )
        if _fire_alert(
            job_id=job_id,
            rule="announcement_high_impact",
            message=msg,
            detail={"item": item, "digest_generated_at": digest.get("generated_at")},
            state_path=state_path,
            rules=rules,
        ):
            fired.append({"rule": "announcement_high_impact", "message": msg, "title": title})

    return fired


def evaluate_var_breaches(
    job_id: str,
    *,
    last_cycle_summary: list[dict[str, Any]],
    state_path: Path = _DEFAULT_STATE,
    rules: ScheduleAlertRules | None = None,
    raw: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Built-in alerts when symbol VaR or portfolio VaR exceeds configured limits."""
    from quant_rd_tool.crypto_var_schedule import get_var_schedule_config

    raw = raw or get_alert_rules()
    rules = rules or ScheduleAlertRules(
        **{k: v for k, v in raw.items() if k in ScheduleAlertRules.__dataclass_fields__}
    )
    if not rules.enabled:
        return []

    cfg = get_var_schedule_config(raw)
    fired: list[dict[str, Any]] = []

    if cfg["on_symbol_var_breach"]:
        max_pct = float(cfg["max_var_pct"])
        for row in last_cycle_summary:
            if row.get("error") or row.get("var_enabled") is False:
                continue
            var_pct = row.get("var_pct")
            if var_pct is None:
                continue
            try:
                if float(var_pct) < max_pct:
                    continue
            except (TypeError, ValueError):
                continue
            sym = row.get("symbol", "")
            msg = (
                f"[{job_id}] {sym} VaR 超限: {float(var_pct) * 100:.2f}% "
                f"(阈值 {max_pct * 100:.2f}%)，约 {row.get('var_usdt')} USDT"
            )
            if _fire_alert(
                job_id=job_id,
                rule="var_symbol_breach",
                message=msg,
                detail={"symbol_row": row, "max_var_pct": max_pct, "var_config": cfg},
                state_path=state_path,
                rules=rules,
            ):
                fired.append({"rule": "var_symbol_breach", "message": msg, "symbol": sym})

    if cfg["on_portfolio_var_breach"]:
        try:
            from quant_rd_tool.crypto_var import build_portfolio_var_report, confidence_key

            report = build_portfolio_var_report(
                testnet=False,
                lookback_bars=cfg["lookback_bars"],
                horizon_days=cfg["horizon_days"],
                confidence_levels=[cfg["confidence"], 0.95],
                mc_n_sims=cfg["mc_n_sims"],
                mc_seed=cfg["mc_seed"],
            )
            if report.get("enabled") and report.get("metrics"):
                key = confidence_key(float(cfg["confidence"]))
                m = report["metrics"].get(key) or report["metrics"].get("0.99") or {}
                equity = report.get("account_equity_usdt")
                var_usdt = m.get("var_usdt")
                ratio = report.get("var_pct_of_equity")
                max_eq = float(cfg["max_portfolio_var_pct_of_equity"])
                breach = False
                if ratio is not None:
                    breach = float(ratio) >= max_eq
                elif equity and var_usdt:
                    breach = float(var_usdt) / float(equity) >= max_eq
                if breach:
                    msg = (
                        f"[{job_id}] 组合 VaR 占权益超限: "
                        f"{(float(ratio or 0) * 100):.1f}% (阈值 {max_eq * 100:.1f}%)，"
                        f"VaR≈{var_usdt} USDT"
                    )
                    if _fire_alert(
                        job_id=job_id,
                        rule="var_portfolio_breach",
                        message=msg,
                        detail={"portfolio_var": report, "max_pct_of_equity": max_eq},
                        state_path=state_path,
                        rules=rules,
                    ):
                        fired.append({"rule": "var_portfolio_breach", "message": msg})
        except Exception as e:
            logger.debug("Portfolio VaR breach check skipped: %s", e)

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
