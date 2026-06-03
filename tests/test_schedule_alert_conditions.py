from quant_rd_tool.schedule_alert_conditions import (
    normalize_symbol,
    row_matches_conditions,
    rule_matches_cycle,
    validate_custom_rule,
)
from quant_rd_tool.schedule_alerts import evaluate_custom_rules, save_alert_rules


def test_normalize_symbol():
    assert normalize_symbol("BTC/USDT") == "BTC"
    assert normalize_symbol("CRYPTO_ETH") == "ETH"


def test_row_matches_and_logic():
    row = {"symbol": "BTC", "stance": "看涨", "action": "buy", "new_bars": 3}
    assert row_matches_conditions(
        row,
        [
            {"field": "symbol", "op": "eq", "value": "BTC"},
            {"field": "stance", "op": "eq", "value": "看涨"},
        ],
        logic="and",
    )
    assert row_matches_conditions(
        row,
        [
            {"field": "stance", "op": "eq", "value": "看跌"},
            {"field": "action", "op": "eq", "value": "sell"},
        ],
        logic="or",
    ) is False


def test_custom_rule_fires(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(
        custom_rules=[
            {
                "id": "btc-bull",
                "enabled": True,
                "conditions": [
                    {"field": "symbol", "op": "eq", "value": "BTC"},
                    {"field": "stance", "op": "eq", "value": "看涨"},
                ],
                "message": "hit {symbol}",
            }
        ],
        cooldown_minutes=0,
    )
    fired = evaluate_custom_rules(
        "job-1",
        last_cycle_summary=[
            {"symbol": "BTC", "pair": "BTC/USDT", "stance": "看涨", "action": "buy"},
            {"symbol": "ETH", "pair": "ETH/USDT", "stance": "中性", "action": "hold"},
        ],
    )
    assert fired and fired[0]["symbol"] == "BTC"


def test_iv_alert_level_condition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(
        custom_rules=[
            {
                "id": "btc-iv-hot",
                "enabled": True,
                "conditions": [
                    {"field": "symbol", "op": "eq", "value": "BTC"},
                    {"field": "iv_alert_level", "op": "eq", "value": "hot"},
                ],
                "message": "IV hot {iv_percentile}",
            }
        ],
        cooldown_minutes=0,
    )
    fired = evaluate_custom_rules(
        "job-1",
        last_cycle_summary=[
            {
                "symbol": "BTC",
                "stance": "中性",
                "action": "hold",
                "iv_alert_level": "hot",
                "iv_percentile": 92,
            },
            {"symbol": "ETH", "iv_alert_level": "normal"},
        ],
    )
    assert fired and fired[0]["symbol"] == "BTC"


def test_var_pct_custom_rule(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_alert_rules(
        custom_rules=[
            {
                "id": "high-var",
                "enabled": True,
                "conditions": [{"field": "var_pct", "op": "gte", "value": 0.04}],
                "message": "VaR {var_pct}",
            }
        ],
        var={"enabled": True},
        cooldown_minutes=0,
    )
    fired = evaluate_custom_rules(
        "job-1",
        last_cycle_summary=[
            {"symbol": "BTC", "stance": "中性", "var_pct": 0.06, "var_usdt": 600},
            {"symbol": "ETH", "var_pct": 0.02},
        ],
    )
    assert fired and fired[0]["symbol"] == "BTC"


def test_evaluate_var_symbol_breach(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.schedule_alerts import evaluate_var_breaches, save_alert_rules

    save_alert_rules(
        var={
            "enabled": True,
            "on_symbol_var_breach": True,
            "max_var_pct": 0.05,
        },
        cooldown_minutes=0,
    )
    fired = evaluate_var_breaches(
        "job-1",
        last_cycle_summary=[
            {"symbol": "BTC", "var_pct": 0.07, "var_usdt": 700, "var_enabled": True},
            {"symbol": "ETH", "var_pct": 0.02, "var_enabled": True},
        ],
    )
    assert len(fired) == 1
    assert fired[0]["rule"] == "var_symbol_breach"


def test_validate_custom_rule():
    assert validate_custom_rule({"id": "x", "conditions": []})
    errs = validate_custom_rule({"conditions": [{"field": "bad", "op": "eq", "value": "1"}]})
    assert "id is required" in errs
    assert any("unsupported" in e for e in errs)
