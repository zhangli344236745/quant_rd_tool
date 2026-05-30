import json
from datetime import date
from pathlib import Path

import pytest

from quant_rd_tool.perp_telemetry import (
    PerpTelemetry,
    TelemetryConfig,
    append_jsonl,
    build_cycle_record,
    build_portfolio_record,
    classify_decision,
    classify_error_category,
    daily_log_path,
)


def test_daily_log_path_format():
    p = daily_log_path("/tmp/logs", day=date(2026, 5, 28))
    assert p.name == "20260528.jsonl"
    assert str(p.parent).endswith("logs")


def test_append_jsonl_writes_one_line(tmp_path: Path):
    log_file = tmp_path / "20260528.jsonl"
    append_jsonl(log_file, {"decision": "no_op", "base": "BTC"})
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["base"] == "BTC"


def test_classify_decision_matrix():
    assert classify_decision({"message": "bar_end 去重"}) == "skipped_dedup"
    assert (
        classify_decision(
            {
                "perp_action": "long",
                "circuit_breaker": {"blocked": True},
                "open_order": None,
                "close_order": None,
            }
        )
        == "blocked_circuit_breaker"
    )
    assert classify_decision({"close_order": {"id": 1}, "open_order": {"id": 2}}) == "flipped"
    assert classify_decision({"open_order": {"id": 1}}) == "opened"
    assert classify_decision({"close_order": {"id": 1}}) == "closed"
    assert classify_decision({}) == "no_op"


def test_classify_error_category_value_error():
    assert classify_error_category(ValueError("bad config")) == "config"


def test_perp_telemetry_emit_cycle(tmp_path: Path):
    tel = PerpTelemetry(TelemetryConfig(enabled=True, log_dir=str(tmp_path)))
    result = {
        "pair": "BTC/USDT:USDT",
        "dry_run": True,
        "testnet": False,
        "bar_end": "2026-05-28 12:00:00",
        "perp_action": "hold",
        "target_side": "flat",
        "message": "dry-run",
        "signal": {"action": "hold", "score": 0, "confidence": 0.5},
    }
    record = tel.log_cycle(result=result, base="BTC", duration_ms=12.5)
    assert record["decision"] == "no_op"
    assert result["decision"] == "no_op"
    assert tel.log_path().exists()
    line = tel.log_path().read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["kind"] == "cycle"
    assert parsed["base"] == "BTC"
    assert parsed["duration_ms"] == 12.5


def test_build_portfolio_record():
    summary = {
        "count": 2,
        "allocation": {"BTC": 100.0},
        "results": [
            {"symbol": "BTC", "result": {"perp_action": "long", "open_order": {"id": 1}}},
            {"symbol": "ETH", "result": {"perp_action": "hold"}},
        ],
    }
    rec = build_portfolio_record(summary)
    assert rec["kind"] == "portfolio"
    assert rec["decisions"][0]["decision"] == "opened"
    assert rec["decisions"][1]["decision"] == "no_op"


def test_build_cycle_record_includes_balance():
    rec = build_cycle_record(
        result={
            "pair": "ETH/USDT:USDT",
            "balance_before": {"USDT_free": 50.0, "USDT_total": 100.0},
            "perp_action": "hold",
        },
        base="eth",
    )
    assert rec["base"] == "ETH"
    assert rec["usdt_total"] == 100.0


@pytest.mark.parametrize("enabled", [False])
def test_telemetry_disabled_writes_nothing(tmp_path: Path, enabled: bool):
    tel = PerpTelemetry(TelemetryConfig(enabled=enabled, log_dir=str(tmp_path)))
    tel.log_cycle(result={"pair": "BTC/USDT:USDT"}, base="BTC")
    assert not list(tmp_path.glob("*.jsonl"))
