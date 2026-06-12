from quant_rd_tool.notification_format import (
    alert_feed_item,
    format_cycle_complete_body,
    format_schedule_alert_bark,
    format_webhook_text,
    rule_meta,
)


def test_rule_meta_known():
    meta = rule_meta("cycle_error")
    assert meta["emoji"] == "🚨"
    assert meta["label"] == "调度周期失败"


def test_cycle_complete_body_structure():
    rows = [
        {"symbol": "BTC", "stance": "看涨", "action": "buy", "new_bars": 3},
        {"symbol": "ETH", "stance": "中性", "action": "hold"},
    ]
    body = format_cycle_complete_body("btc-5m", rows)
    assert "BTC" in body
    assert "📈" in body
    assert "────────────────" in body
    assert "btc-5m" in body


def test_schedule_alert_bark_cycle_complete():
    rows = [{"symbol": "BTC", "stance": "看涨", "action": "buy"}]
    bark = format_schedule_alert_bark(
        job_id="job-1",
        rule="cycle_complete",
        message="ignored",
        detail={"symbols": rows},
    )
    assert bark["title"].startswith("📊")
    assert bark["subtitle"] == "job-1"
    assert "BTC" in bark["body"]
    assert bark["level"] == "passive"


def test_schedule_alert_bark_error():
    bark = format_schedule_alert_bark(
        job_id="job-1",
        rule="cycle_error",
        message="[job-1] 调度周期失败: boom",
        detail={"last_error": "boom"},
    )
    assert "🚨" in bark["title"]
    assert bark["level"] == "timeSensitive"
    assert "boom" in bark["body"]


def test_webhook_perp_markdown():
    text = format_webhook_text(
        {
            "kind": "cycle",
            "base": "BTC",
            "decision": "opened",
            "signal_action": "buy",
            "signal_confidence": 0.72,
            "message": "已执行",
        }
    )
    assert "**" in text
    assert "BTC" in text
    assert "opened" in text or "开仓" in text


def test_webhook_test_message():
    text = format_webhook_text({"kind": "test"})
    assert "测试" in text or "Webhook" in text


def test_alert_feed_item_enrichment():
    item = alert_feed_item(
        {
            "ts": "2026-06-12T10:00:00+00:00",
            "job_id": "j1",
            "rule": "cycle_complete",
            "message": "line1\nline2",
        }
    )
    assert item["rule_label"] == "分析完成"
    assert item["rule_emoji"] == "📊"
    assert item["message_lines"] == ["line1", "line2"]
