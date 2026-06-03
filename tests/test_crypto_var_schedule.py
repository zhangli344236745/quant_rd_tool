from quant_rd_tool.crypto_var_schedule import (
    _rule_uses_var_field,
    var_cycle_needed,
)


def test_rule_uses_var_field():
    assert _rule_uses_var_field(
        {"conditions": [{"field": "var_pct", "op": "gte", "value": 0.05}]}
    )
    assert not _rule_uses_var_field(
        {"conditions": [{"field": "stance", "op": "eq", "value": "看涨"}]}
    )


def test_var_cycle_needed_with_var_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.schedule_alerts import save_alert_rules

    save_alert_rules(var={"enabled": True})
    assert var_cycle_needed() is True


def test_var_cycle_needed_with_custom_rule(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.schedule_alerts import save_alert_rules

    save_alert_rules(
        custom_rules=[
            {
                "id": "v",
                "conditions": [{"field": "var_99_pct", "op": "gte", "value": 0.03}],
            }
        ],
    )
    assert var_cycle_needed() is True
