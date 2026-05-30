import json
from datetime import date

from quant_rd_tool.crypto_ops import (
    build_ops_summary,
    list_perp_states,
    summarize_telemetry,
    tail_jsonl,
)


def test_tail_jsonl(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    p = log_dir / "20260530.jsonl"
    p.write_text(
        '{"decision":"opened","ts":"t1"}\n{"decision":"no_op","ts":"t2"}\n',
        encoding="utf-8",
    )
    rows = tail_jsonl(log_dir, day=date(2026, 5, 30), limit=10)
    assert len(rows) == 2
    assert rows[-1]["decision"] == "no_op"


def test_summarize_telemetry():
    s = summarize_telemetry(
        [{"decision": "opened"}, {"decision": "blocked_circuit_breaker", "error_category": "transient"}]
    )
    assert s["total"] == 2
    assert s["circuit_breaker_blocks"] == 1
    assert s["error_count"] == 1


def test_list_perp_states(tmp_path):
    (tmp_path / "perp_state_BTC.json").write_text(
        json.dumps({"last_seen_bar_end": "2026-05-30", "position": {"side": "long"}}),
        encoding="utf-8",
    )
    items = list_perp_states(tmp_path)
    assert len(items) == 1
    assert items[0]["base"] == "BTC"


def test_build_ops_summary_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "crypto").mkdir(parents=True)
    out = build_ops_summary(data_dir="data/crypto", log_dir="data/crypto/perp_logs")
    assert out["schedules"]["total"] >= 0
    assert "telemetry_summary" in out
