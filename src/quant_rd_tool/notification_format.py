"""Rich notification formatting for Bark, Webhook, and in-app alert feeds.

Plain one-line messages like ``[job] cycle_error: boom`` are hard to scan on
mobile. This module builds structured titles, subtitles, and multi-line bodies
with consistent severity, emoji cues, and markdown-friendly webhook text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

Severity = Literal["info", "success", "warning", "critical"]

RULE_META: dict[str, dict[str, str]] = {
    "cycle_error": {"label": "调度周期失败", "emoji": "🚨", "severity": "critical"},
    "worker_crash": {"label": "调度线程异常", "emoji": "💥", "severity": "critical"},
    "consecutive_failures": {"label": "连续失败", "emoji": "🔁", "severity": "critical"},
    "stale_running": {"label": "任务卡住", "emoji": "⏳", "severity": "warning"},
    "cycle_complete": {"label": "分析完成", "emoji": "📊", "severity": "success"},
    "stance_changed": {"label": "立场变化", "emoji": "🔀", "severity": "warning"},
    "custom_signal": {"label": "自定义信号", "emoji": "🎯", "severity": "warning"},
    "var_breach": {"label": "VaR 超限", "emoji": "⚠️", "severity": "warning"},
    "news_high_impact": {"label": "高影响舆情", "emoji": "📰", "severity": "warning"},
    "options_spread_alert": {"label": "期权价差", "emoji": "📐", "severity": "warning"},
    "schedule_alert": {"label": "调度告警", "emoji": "🔔", "severity": "warning"},
    "test": {"label": "连通测试", "emoji": "✅", "severity": "info"},
}

DECISION_META: dict[str, dict[str, str]] = {
    "opened": {"label": "开仓", "emoji": "🟢", "severity": "success"},
    "flipped": {"label": "换向", "emoji": "🔄", "severity": "warning"},
    "closed": {"label": "平仓", "emoji": "🟠", "severity": "info"},
    "blocked_circuit_breaker": {"label": "熔断拦截", "emoji": "🛑", "severity": "warning"},
    "error": {"label": "执行错误", "emoji": "❌", "severity": "critical"},
    "skipped_dedup": {"label": "周期去重", "emoji": "⏭️", "severity": "info"},
    "no_op": {"label": "无操作", "emoji": "💤", "severity": "info"},
}

STANCE_EMOJI: dict[str, str] = {
    "看涨": "📈",
    "看跌": "📉",
    "中性": "➖",
    "模型偏多": "🤖↑",
    "模型偏空": "🤖↓",
}

ACTION_EMOJI: dict[str, str] = {
    "buy": "🟢",
    "sell": "🔴",
    "hold": "⚪",
    "long": "🟢",
    "short": "🔴",
}


def rule_meta(rule: str) -> dict[str, str]:
    key = (rule or "").strip()
    if key in RULE_META:
        return RULE_META[key]
    return {"label": key or "告警", "emoji": "🔔", "severity": "warning"}


def decision_meta(decision: str) -> dict[str, str]:
    key = (decision or "").strip()
    if key in DECISION_META:
        return DECISION_META[key]
    return {"label": key or "事件", "emoji": "ℹ️", "severity": "info"}


def bark_level(severity: str) -> str:
    if severity == "critical":
        return "timeSensitive"
    if severity == "warning":
        return "active"
    return "passive"


def _divider() -> str:
    return "────────────────"


def _fmt_ts(raw: str | None = None) -> str:
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC).strftime("%m-%d %H:%M UTC")
        except ValueError:
            pass
    return datetime.now(UTC).strftime("%m-%d %H:%M UTC")


def _stance_line(row: dict[str, Any]) -> str:
    sym = str(row.get("symbol") or row.get("pair") or "?").upper()
    stance = str(row.get("stance") or "—")
    action = str(row.get("action") or "—")
    s_emoji = STANCE_EMOJI.get(stance, "")
    a_emoji = ACTION_EMOJI.get(action.lower(), "")
    new_bars = row.get("new_bars")
    extra = ""
    if new_bars not in (None, 0, "0", ""):
        extra = f"  ·  +{new_bars} bars"
    iv = row.get("iv_alert_level")
    if iv:
        extra += f"  ·  IV {iv}"
    return f"{sym:6}  {s_emoji} {stance:4}  {a_emoji} {action}{extra}"


def format_cycle_complete_body(job_id: str, rows: list[dict[str, Any]]) -> str:
    """Multi-line Bark/Webhook body after a successful schedule cycle."""
    lines = [_divider()]
    for row in rows[:12]:
        lines.append(_stance_line(row))
    if len(rows) > 12:
        lines.append(f"… 另有 {len(rows) - 12} 个标的")
    lines.append(_divider())
    lines.append(f"任务 {job_id}  ·  {len(rows)} 标的  ·  {_fmt_ts()}")
    return "\n".join(lines)


def format_schedule_alert_bark(
    *,
    job_id: str,
    rule: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = rule_meta(rule)
    severity = meta["severity"]
    title = f"{meta['emoji']} {meta['label']}"
    subtitle = job_id or "quant-rd"

    body_lines: list[str] = []
    if rule == "cycle_complete" and detail and detail.get("symbols"):
        body_lines.append(format_cycle_complete_body(job_id, list(detail["symbols"])))
    else:
        clean = (message or "").strip()
        if clean.startswith(f"[{job_id}]"):
            clean = clean[len(f"[{job_id}]") :].strip(" :")
        if clean:
            body_lines.append(clean)
        if detail:
            extra = _detail_lines(detail, exclude={"symbols"})
            if extra:
                if body_lines:
                    body_lines.append("")
                body_lines.extend(extra)
        if not body_lines:
            body_lines.append("（无附加说明）")
        body_lines.append("")
        body_lines.append(f"{_fmt_ts()}  ·  {job_id}")

    return {
        "title": title[:200],
        "subtitle": subtitle[:100],
        "body": "\n".join(body_lines)[:4000],
        "group": "schedule",
        "level": bark_level(severity),
    }


def format_webhook_text(payload: dict[str, Any]) -> str:
    """Markdown-friendly summary for Slack/Discord/generic webhooks."""
    kind = str(payload.get("kind") or "alert")
    if kind == "schedule_alert":
        return _format_schedule_webhook(payload)
    if kind in ("cycle", "perp") or payload.get("decision"):
        return _format_perp_webhook(payload)
    if kind == "options_spread_alert":
        return _format_options_webhook(payload)
    if kind == "test":
        return "**✅ quant-rd Webhook 测试**\n\n推送通道已连通，运营告警将按规则发送到此 URL。"
    return _format_generic_webhook(payload)


def _format_schedule_webhook(payload: dict[str, Any]) -> str:
    rule = str(payload.get("decision") or payload.get("rule") or "alert")
    meta = rule_meta(rule)
    job_id = str(payload.get("job_id") or "")
    lines = [
        f"**{meta['emoji']} {meta['label']}**",
        f"任务 `{job_id}`" if job_id else "",
        _divider(),
    ]
    message = str(payload.get("message") or "").strip()
    if message:
        lines.append(message)
    detail = payload.get("detail")
    if isinstance(detail, dict):
        extra = _detail_lines(detail, exclude={"symbols"})
        if extra:
            lines.append("")
            lines.extend(extra)
        symbols = detail.get("symbols")
        if isinstance(symbols, list) and symbols:
            lines.append("")
            lines.extend(_stance_line(r) for r in symbols[:8])
            if len(symbols) > 8:
                lines.append(f"…共 {len(symbols)} 标的")
    lines.append("")
    lines.append(f"_{_fmt_ts()}_")
    return "\n".join(l for l in lines if l is not None)


def _format_perp_webhook(payload: dict[str, Any]) -> str:
    decision = str(payload.get("decision") or "")
    meta = decision_meta(decision)
    base = str(payload.get("base") or payload.get("symbol") or "").upper()
    lines = [
        f"**{meta['emoji']} 永续 Bot · {base or '—'}**",
        f"决策 **{meta['label']}** (`{decision}`)" if decision else "",
        _divider(),
    ]
    signal = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}
    sig_action = signal.get("action") or payload.get("signal_action")
    sig_conf = signal.get("confidence") or payload.get("signal_confidence")
    if sig_action:
        conf_txt = f" · 置信 {float(sig_conf):.0%}" if sig_conf is not None else ""
        lines.append(f"信号 {sig_action}{conf_txt}")
    perp_action = payload.get("perp_action")
    if perp_action:
        lines.append(f"目标动作 {perp_action}")
    msg = payload.get("message")
    if msg:
        lines.append(str(msg))
    err = payload.get("error_category") or payload.get("error_message") or payload.get("error")
    if err:
        lines.append(f"错误 {err}")
    cb = payload.get("circuit_breaker")
    if isinstance(cb, dict) and cb.get("blocked"):
        lines.append(f"熔断 {cb.get('reason', 'blocked')}")
    sizing = payload.get("sizing") or {}
    if isinstance(sizing, dict) and sizing.get("notional_usdt"):
        lines.append(f"名义 {sizing['notional_usdt']} USDT · {sizing.get('mode', '')}")
    lines.append("")
    lines.append(f"_{_fmt_ts(payload.get('ts'))}_")
    return "\n".join(l for l in lines if l)


def _format_options_webhook(payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or "期权价差告警")
    message = str(payload.get("message") or "")
    base = str(payload.get("base") or "")
    lines = [
        f"**📐 {title}**",
        f"标的 `{base}`" if base else "",
        _divider(),
        message,
        "",
        f"_{_fmt_ts()}_",
    ]
    return "\n".join(l for l in lines if l)


def _format_generic_webhook(payload: dict[str, Any]) -> str:
    parts = [f"**🔔 quant-rd**"]
    for key in ("kind", "base", "symbol", "decision", "job_id", "message"):
        val = payload.get(key)
        if val:
            parts.append(f"{key}: {val}")
    parts.append(f"_{_fmt_ts()}_")
    return "\n".join(parts)


def _detail_lines(detail: dict[str, Any], *, exclude: set[str] | None = None) -> list[str]:
    skip = exclude or set()
    lines: list[str] = []
    if detail.get("last_error"):
        lines.append(f"错误: {detail['last_error']}")
    if detail.get("streak") is not None:
        lines.append(f"连续失败 {detail['streak']} 次")
    if detail.get("status"):
        lines.append(f"状态 {detail['status']}")
    for key, label in (
        ("var_pct", "VaR"),
        ("var_usdt", "VaR USDT"),
        ("score", "评分"),
        ("headline", "标题"),
    ):
        if key in skip:
            continue
        if detail.get(key) not in (None, ""):
            lines.append(f"{label}: {detail[key]}")
    return lines


def format_test_bark() -> dict[str, Any]:
    return {
        "title": "✅ quant-rd 已连通",
        "subtitle": "Bark 推送测试",
        "body": "\n".join(
            [
                "调度分析、VaR 超限、舆情高影响等告警",
                "将推送到此设备。",
                "",
                _divider(),
                _fmt_ts(),
            ]
        ),
        "group": "schedule",
        "level": "passive",
    }


def alert_feed_item(entry: dict[str, Any]) -> dict[str, Any]:
    """Enrich alert log rows for UI display."""
    rule = str(entry.get("rule") or "")
    meta = rule_meta(rule)
    message = str(entry.get("message") or "")
    preview = message.split("\n", 1)[0].strip()
    if len(preview) > 120:
        preview = preview[:117] + "…"
    return {
        **entry,
        "rule_label": meta["label"],
        "rule_emoji": meta["emoji"],
        "severity": meta["severity"],
        "message_preview": preview,
        "message_lines": [ln for ln in message.split("\n") if ln.strip()],
    }
