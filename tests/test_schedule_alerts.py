import json

import pytest
from unittest.mock import patch

from quant_rd_tool.schedule_alerts import (
    evaluate_after_cycle,
    evaluate_news_alerts,
    evaluate_stale_jobs,
    get_alert_rules,
    save_alert_rules,
    send_test_bark,
    tail_alert_log,
)


def test_save_and_load_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(consecutive_failures=2, stale_minutes=60)
    rules = get_alert_rules()
    assert rules["consecutive_failures"] == 2
    assert rules["stale_minutes"] == 60


def test_consecutive_failure_alert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(consecutive_failures=2, cooldown_minutes=0)
    fired = evaluate_after_cycle(
        "job-a",
        last_error="sync failed",
        last_cycle_summary=[{"symbol": "BTC", "error": "x"}],
        status="running",
    )
    assert not any(f["rule"] == "consecutive_failures" for f in fired)
    fired = evaluate_after_cycle(
        "job-a",
        last_error="sync failed",
        last_cycle_summary=[],
        status="running",
    )
    assert any(f["rule"] == "consecutive_failures" for f in fired)
    assert len(tail_alert_log()) >= 1


def test_stale_running_alert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(stale_minutes=30, cooldown_minutes=0)
    jobs = [
        {
            "id": "btc-5m",
            "status": "running",
            "last_run_at": "2020-01-01T00:00:00+00:00",
        }
    ]
    fired = evaluate_stale_jobs(jobs)
    assert fired and fired[0]["rule"] == "stale_running"


def test_webhook_on_alert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.crypto_ops_control import save_crypto_ops

    save_crypto_ops(webhook_url="https://example.com/hook")
    save_alert_rules(on_cycle_error=True, cooldown_minutes=0)
    with patch("quant_rd_tool.crypto_ops_control.post_webhook") as post:
        evaluate_after_cycle(
            "j1",
            last_error="boom",
            last_cycle_summary=None,
            status="error",
        )
        assert post.called


def test_webhook_on_alert_can_disable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.crypto_ops_control import save_crypto_ops

    save_crypto_ops(webhook_url="https://example.com/hook")
    save_alert_rules(
        on_cycle_error=True,
        cooldown_minutes=0,
        webhook_on_alert=False,
    )
    with patch("quant_rd_tool.crypto_ops_control.post_webhook") as post:
        evaluate_after_cycle(
            "j1",
            last_error="boom",
            last_cycle_summary=None,
            status="error",
        )
        assert not post.called


def test_cycle_complete_bark_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(
        on_cycle_error=False,
        on_cycle_complete=True,
        cooldown_minutes=0,
        bark={"enabled": True, "device_key": "k1"},
    )
    summary = [
        {"symbol": "BTC", "stance": "看涨", "action": "buy", "new_bars": 3},
        {"symbol": "ETH", "stance": "中性", "action": "hold", "new_bars": 0},
    ]
    with patch("quant_rd_tool.bark_push.post_bark") as post_bark:
        fired = evaluate_after_cycle(
            "job-1",
            last_error=None,
            last_cycle_summary=summary,
            status="running",
        )
        assert any(f["rule"] == "cycle_complete" for f in fired)
        assert post_bark.called


def test_cycle_complete_skipped_on_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(
        on_cycle_error=False,
        on_cycle_complete=True,
        cooldown_minutes=0,
        bark={"enabled": True, "device_key": "k1"},
    )
    fired = evaluate_after_cycle(
        "job-1",
        last_error="sync failed",
        last_cycle_summary=[{"symbol": "BTC", "error": "x"}],
        status="running",
    )
    assert not any(f.get("rule") == "cycle_complete" for f in fired)


def test_bark_on_alert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(
        on_cycle_error=True,
        cooldown_minutes=0,
        webhook_on_alert=False,
        bark={"enabled": True, "device_key": "abc123"},
    )
    with patch("quant_rd_tool.bark_push.post_bark") as post_bark:
        evaluate_after_cycle(
            "j1",
            last_error="boom",
            last_cycle_summary=None,
            status="error",
        )
        assert post_bark.called
        assert post_bark.call_args.kwargs.get("group") == "schedule"


def test_bark_disabled_skips_push(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(
        on_cycle_error=True,
        cooldown_minutes=0,
        bark={"enabled": False, "device_key": "abc123"},
    )
    with patch("quant_rd_tool.bark_push.post_bark") as post_bark:
        evaluate_after_cycle(
            "j1",
            last_error="boom",
            last_cycle_summary=None,
            status="error",
        )
        assert not post_bark.called


def test_save_bark_requires_key_when_enabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "quant_rd_tool.schedule_alerts._bark_from_env",
        lambda: {"device_key": "", "server": ""},
    )
    with pytest.raises(ValueError, match="device_key"):
        save_alert_rules(bark={"enabled": True, "device_key": ""})


def test_send_test_bark(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("quant_rd_tool.bark_push.post_bark", return_value={"code": 200}) as post:
        result = send_test_bark({"enabled": True, "device_key": "key99"})
        assert result == {"code": 200}
        assert post.called


def test_send_test_bark_requires_device_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "quant_rd_tool.schedule_alerts._bark_from_env",
        lambda: {"device_key": "", "server": ""},
    )
    with pytest.raises(ValueError, match="Device Key"):
        send_test_bark({"enabled": False, "device_key": ""})


def test_send_test_bark_without_enabled_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("quant_rd_tool.bark_push.post_bark", return_value={"code": 200}) as post:
        send_test_bark({"device_key": "key-only"})
        assert post.called


def test_bark_device_key_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "quant_rd_tool.schedule_alerts._bark_from_env",
        lambda: {"device_key": "env-secret-key", "server": ""},
    )
    save_alert_rules(bark={"enabled": True})
    rules = get_alert_rules()
    assert rules["bark"]["device_key"] == ""
    assert rules["bark"]["device_key_from_env"] is True
    assert rules["bark"]["device_key_configured"] is True

    with patch("quant_rd_tool.bark_push.post_bark", return_value={"code": 200}) as post:
        send_test_bark({})
        assert post.call_args[0][0] == "env-secret-key"


def test_schedule_alerts_http_routes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "quant_rd_tool.schedule_alerts._bark_from_env",
        lambda: {"device_key": "", "server": ""},
    )
    from fastapi.testclient import TestClient

    from quant_rd_tool.main import app

    client = TestClient(app)
    for path in (
        "/api/v1/crypto/schedules/alerts/rules",
        "/api/v1/crypto/schedules/alerts/log?limit=5",
        "/api/v1/crypto/schedules/alerts/rules/format",
    ):
        r = client.get(path)
        assert r.status_code == 200, f"{path}: {r.text}"

    r = client.post("/api/v1/crypto/schedules/alerts/test-bark", json={})
    assert r.status_code == 400

    with patch("quant_rd_tool.bark_push.post_bark", return_value={"code": 200}):
        r = client.post(
            "/api/v1/crypto/schedules/alerts/test-bark",
            json={"bark": {"enabled": True, "device_key": "abc"}},
        )
        assert r.status_code == 200, r.text
        rules = get_alert_rules()
        assert rules["bark"]["device_key"] == "abc"

        r2 = client.post(
            "/api/v1/crypto/schedules/alerts/test-bark?device_key=querykey",
            json={},
        )
        assert r2.status_code == 200, r2.text


def test_news_high_impact_alert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(
        cooldown_minutes=0,
        bark={"enabled": True, "device_key": "k1"},
        crypto_news={"on_high_impact": True, "min_score": 70, "min_llm_confidence": 0.8},
    )
    digest = {
        "generated_at": "2026-06-03T12:00:00+00:00",
        "top_items": [
            {
                "title": "Fed raises rates",
                "score": 85,
                "advice": {"impact": "bearish", "confidence": 0.9, "headline": "Fed raises rates"},
            },
            {
                "title": "Minor market note",
                "score": 50,
                "advice": {"impact": "neutral", "confidence": 0.5},
            },
        ],
    }
    with patch("quant_rd_tool.bark_push.post_bark") as post_bark:
        fired = evaluate_news_alerts("news-job", digest)
    assert any(f["rule"] == "news_high_impact" for f in fired)
    assert post_bark.called
    assert len(fired) == 1


def test_news_high_impact_respects_thresholds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(
        cooldown_minutes=0,
        crypto_news={"on_high_impact": True, "min_score": 90, "min_llm_confidence": 0.95},
    )
    digest = {
        "top_items": [
            {"title": "Fed raises rates", "score": 85, "advice": {"confidence": 0.9}},
        ],
    }
    with patch("quant_rd_tool.bark_push.post_bark") as post_bark:
        fired = evaluate_news_alerts("news-job", digest)
    assert fired == []
    assert not post_bark.called


def test_run_news_cycle_evaluates_alerts(tmp_path):
    config = {"enabled": True, "min_score": 40, "llm_top_n": 1, "feeds": []}
    digest = {
        "generated_at": "2026-06-03T12:00:00+00:00",
        "top_items": [{"title": "X", "score": 80, "advice": {"confidence": 0.9}}],
    }
    expected = {"items_processed": 1, "digest": digest}
    with patch("quant_rd_tool.crypto_news_scheduler.get_crypto_news_config", return_value=config):
        with patch("quant_rd_tool.crypto_news_scheduler.run_news_scan", return_value=expected):
            with patch("quant_rd_tool.schedule_alerts.evaluate_news_alerts") as mock_alert:
                from quant_rd_tool.crypto_news_scheduler import run_news_cycle

                run_news_cycle(data_dir=tmp_path, job_id="j-news")
    mock_alert.assert_called_once_with("j-news", digest)
