import json
from unittest.mock import patch

from quant_rd_tool.schedule_alerts import (
    evaluate_after_cycle,
    evaluate_stale_jobs,
    get_alert_rules,
    save_alert_rules,
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


def test_schedule_alerts_http_routes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
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
