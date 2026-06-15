"""Stance change alerting for schedule jobs."""

from __future__ import annotations

from unittest.mock import patch

from quant_rd_tool.schedule_alerts import evaluate_stance_changes, save_alert_rules


def test_stance_changed_fires_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(cooldown_minutes=0, on_stance_changed=True, bark={"enabled": False})
    summary = [{"symbol": "SH600519", "stance": "中性"}]
    assert evaluate_stance_changes("job1", last_cycle_summary=summary) == []

    summary2 = [{"symbol": "SH600519", "stance": "偏多"}]
    with patch("quant_rd_tool.schedule_alerts._deliver_schedule_notifications"):
        fired = evaluate_stance_changes("job1", last_cycle_summary=summary2)
    assert any(f["rule"] == "stance_changed" for f in fired)
