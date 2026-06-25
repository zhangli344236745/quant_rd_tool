from __future__ import annotations

import json

from quant_rd_tool import crypto_polymarket_arb as pa
from quant_rd_tool.crypto_polymarket_analytics import (
    append_edge_history,
    edge_trend,
    leaderboard,
)


def test_append_edge_history_and_trend(monkeypatch, tmp_path):
    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    row = {
        "opportunity": True,
        "condition_id": "c1",
        "question": "Q?",
        "strategy_type": "binary_ask",
        "edge_bps": 40,
        "edge_at_size_bps": 35,
        "profit_at_size_usd": 1.2,
    }
    append_edge_history(row)
    path = tmp_path / "edge_history.jsonl"
    assert path.is_file()
    items = edge_trend("c1", hours=24)
    assert len(items) == 1
    assert items[0]["edge_bps"] == 40


def test_leaderboard(monkeypatch, tmp_path):
    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    lines = [
        {"ts": "2026-06-25T10:00:00+08:00", "condition_id": "c1", "question": "A", "strategy_type": "binary_ask", "edge_bps": 30, "edge_at_size_bps": 28},
        {"ts": "2026-06-25T11:00:00+08:00", "condition_id": "c1", "question": "A", "strategy_type": "binary_ask", "edge_bps": 45, "edge_at_size_bps": 40},
        {"ts": "2026-06-25T10:30:00+08:00", "condition_id": "c2", "question": "B", "strategy_type": "binary_bid", "edge_bps": 20, "edge_at_size_bps": 18},
    ]
    (tmp_path / "edge_history.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines) + "\n",
        encoding="utf-8",
    )
    rows = leaderboard(hours=720, limit=10)
    assert rows[0]["condition_id"] == "c1"
    assert rows[0]["hit_count"] == 2
