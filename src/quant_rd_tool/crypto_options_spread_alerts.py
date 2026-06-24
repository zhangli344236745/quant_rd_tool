"""Push alerts when cross-venue aligned IV spread exceeds thresholds."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

AlertLevel = Literal["elevated", "hot"]

_DEFAULT_CONFIG = {
    "enabled": True,
    "elevated_pp": 2.5,
    "hot_pp": 5.0,
    "cooldown_minutes": 60,
    "symbols": ["BTC", "ETH", "SOL", "BNB"],
    "webhook_on_alert": True,
    "bark_on_alert": True,
}

_STATE_PATH = Path("data/crypto/options_spread_alert_state.json")
_LOG_PATH = Path("data/crypto/options_spread_alert_log.jsonl")


def _settings_path(data_dir: str | Path = "data/crypto") -> Path:
    return Path(data_dir).parent / "settings.json"


def get_spread_alert_config(data_dir: str = "data/crypto") -> dict[str, Any]:
    cfg = dict(_DEFAULT_CONFIG)
    path = _settings_path(data_dir)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            ent = raw.get("crypto_options_spread_alerts") or {}
            if isinstance(ent, dict):
                cfg.update({k: ent[k] for k in cfg if k in ent})
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_spread_alert_config(*, data_dir: str = "data/crypto", **updates: Any) -> dict[str, Any]:
    path = _settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
    ent = raw.get("crypto_options_spread_alerts")
    if not isinstance(ent, dict):
        ent = {}
    cfg = get_spread_alert_config(data_dir)
    for k in _DEFAULT_CONFIG:
        if k in updates and updates[k] is not None:
            ent[k] = updates[k]
            cfg[k] = updates[k]
    ent["updated_at"] = now_iso()
    raw["crypto_options_spread_alerts"] = ent
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def _load_state(path: Path | None = None) -> dict[str, Any]:
    path = path or _STATE_PATH
    if not path.is_file():
        return {"last_alerts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"last_alerts": {}}
    except (json.JSONDecodeError, OSError):
        return {"last_alerts": {}}


def _save_state(state: dict[str, Any], path: Path | None = None) -> None:
    path = path or _STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def append_spread_alert_log(entry: dict[str, Any], *, log_path: Path | None = None) -> None:
    log_path = log_path or _LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": now_iso(), **entry}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def tail_spread_alert_log(*, limit: int = 50, log_path: Path | None = None) -> list[dict[str, Any]]:
    log_path = log_path or _LOG_PATH
    if not log_path.is_file():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) :]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _cooldown_ok(state: dict[str, Any], key: str, *, cooldown_minutes: int) -> bool:
    prev = (state.get("last_alerts") or {}).get(key)
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


def _classify_spread(abs_pp: float, cfg: dict[str, Any]) -> AlertLevel | None:
    hot = float(cfg.get("hot_pp") or 5.0)
    elevated = float(cfg.get("elevated_pp") or 2.5)
    if abs_pp >= hot:
        return "hot"
    if abs_pp >= elevated:
        return "elevated"
    return None


def _deliver_notification(
    *,
    title: str,
    message: str,
    detail: dict[str, Any],
    cfg: dict[str, Any],
) -> None:
    if cfg.get("webhook_on_alert", True):
        try:
            from quant_rd_tool.crypto_ops_control import get_crypto_ops, post_webhook

            ops = get_crypto_ops()
            url = (ops.get("webhook_url") or "").strip()
            if url:
                post_webhook(
                    url,
                    {
                        "kind": "options_spread_alert",
                        "title": title,
                        "message": message,
                        **detail,
                    },
                )
        except Exception:
            logger.debug("spread alert webhook failed", exc_info=True)

    if not cfg.get("bark_on_alert", True):
        return
    try:
        from quant_rd_tool.notification_format import format_schedule_alert_bark
        from quant_rd_tool.schedule_alerts import get_alert_rules
        from quant_rd_tool.bark_push import post_bark

        rules = get_alert_rules()
        bark_cfg = rules.get("bark") if isinstance(rules.get("bark"), dict) else {}
        if not bark_cfg.get("enabled") or not bark_cfg.get("device_key"):
            return
        base = str(detail.get("base") or "")
        bark = format_schedule_alert_bark(
            job_id=base or "options",
            rule="options_spread_alert",
            message=message,
            detail={"headline": title, **detail},
        )
        post_bark(
            str(bark_cfg["device_key"]),
            title=bark["title"],
            body=bark["body"],
            subtitle=bark.get("subtitle"),
            level=bark.get("level"),
            server=str(bark_cfg.get("server") or "https://api.day.app"),
            group="options-spread",
        )
    except Exception:
        logger.warning("spread alert bark failed", exc_info=True)


def fire_spread_alert(
    *,
    base: str,
    level: AlertLevel,
    message: str,
    detail: dict[str, Any] | None = None,
    data_dir: str = "data/crypto",
    cfg: dict[str, Any] | None = None,
) -> bool:
    """Fire one spread alert if enabled and cooldown permits."""
    cfg = cfg or get_spread_alert_config(data_dir)
    if not cfg.get("enabled", True):
        return False
    symbols = [str(s).upper() for s in (cfg.get("symbols") or [])]
    if symbols and base.upper() not in symbols:
        return False

    state = _load_state()
    key = f"{base.upper()}:{level}"
    cooldown = max(1, int(cfg.get("cooldown_minutes") or 60))
    if not _cooldown_ok(state, key, cooldown_minutes=cooldown):
        return False

    detail = detail or {}
    title = f"[{base}] 跨所IV价差 {level.upper()}"
    append_spread_alert_log(
        {
            "base": base.upper(),
            "level": level,
            "message": message,
            "detail": detail,
        }
    )
    _deliver_notification(title=title, message=message, detail=detail, cfg=cfg)

    state.setdefault("last_alerts", {})[key] = now_iso()
    _save_state(state)
    return True


def evaluate_compare_item(
    item: dict[str, Any],
    *,
    data_dir: str = "data/crypto",
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Check one venue compare item; fire alert if threshold met."""
    cfg = cfg or get_spread_alert_config(data_dir)
    if not cfg.get("enabled", True):
        return None
    base = str(item.get("base") or "").upper()
    if not base:
        return None

    cmp = item.get("comparison") or {}
    aligned = item.get("aligned") if isinstance(item.get("aligned"), dict) else None
    if aligned and aligned.get("available"):
        cmp = aligned.get("comparison") or cmp
        expiry = aligned.get("expiry_date")
    else:
        expiry = cmp.get("expiry_date")

    abs_pp = cmp.get("abs_spread_pp")
    if abs_pp is None and cmp.get("iv_spread_pp") is not None:
        abs_pp = abs(float(cmp["iv_spread_pp"]))
    if abs_pp is None:
        return None

    level = _classify_spread(float(abs_pp), cfg)
    if not level:
        return None

    spread_pp = cmp.get("iv_spread_pp")
    spread_txt = f"{float(spread_pp):+.1f}" if spread_pp is not None else "—"
    richer = cmp.get("richer_venue") or "—"
    summary = cmp.get("summary") or ""
    message = (
        f"{base} 同到期 {expiry or '—'}：Binance−Deribit IV 差 {spread_txt}pp，"
        f"{richer} 偏高（|Δ|={float(abs_pp):.1f}pp，{level}）。"
    )
    if summary:
        message = f"{message}\n{summary}"

    fired = fire_spread_alert(
        base=base,
        level=level,
        message=message,
        detail={
            "base": base,
            "level": level,
            "expiry_date": expiry,
            "iv_spread_pp": spread_pp,
            "abs_spread_pp": abs_pp,
            "richer_venue": richer,
            "mode": cmp.get("mode") or ("aligned_expiry" if aligned else "near_month"),
        },
        data_dir=data_dir,
        cfg=cfg,
    )
    return {"base": base, "level": level, "fired": fired, "message": message}


def process_spread_alerts(
    compare_pack: dict[str, Any],
    *,
    data_dir: str = "data/crypto",
) -> dict[str, Any]:
    """Evaluate all items in a venue compare scan; return summary of fired alerts."""
    cfg = get_spread_alert_config(data_dir)
    results: list[dict[str, Any]] = []
    for item in compare_pack.get("items") or []:
        if not isinstance(item, dict):
            continue
        r = evaluate_compare_item(item, data_dir=data_dir, cfg=cfg)
        if r:
            results.append(r)
    return {
        "checked": len(compare_pack.get("items") or []),
        "triggered": len(results),
        "fired": sum(1 for r in results if r.get("fired")),
        "results": results,
    }


def send_test_spread_alert(*, data_dir: str = "data/crypto") -> dict[str, Any]:
    """Send a test notification bypassing cooldown (does not update state)."""
    cfg = get_spread_alert_config(data_dir)
    message = "测试：跨所 IV 价差告警通道正常（Binance × Deribit）。"
    _deliver_notification(
        title="[TEST] 期权价差告警",
        message=message,
        detail={"test": True},
        cfg=cfg,
    )
    append_spread_alert_log(
        {"base": "TEST", "level": "test", "message": message, "detail": {"test": True}}
    )
    return {"status": "ok", "message": message}
