from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from quant_rd_tool.crypto_polymarket_backtest import (
    build_advisor_calibration,
    build_roi_distribution,
    build_strategy_backtest,
    load_opportunity_history,
)


def _write_opportunities(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_load_opportunity_history_filters_by_hours(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_backtest as bt

    monkeypatch.setattr(bt, "POLYMARKET_DIR", tmp_path)
    old_ts = (datetime.now(UTC) - timedelta(hours=200)).isoformat()
    new_ts = datetime.now(UTC).isoformat()
    _write_opportunities(
        tmp_path / "opportunities.jsonl",
        [
            {"ts": old_ts, "opportunity": True, "strategy_type": "binary_ask", "edge_bps": 30},
            {"ts": new_ts, "opportunity": True, "strategy_type": "binary_bid", "edge_bps": 40},
        ],
    )
    rows = load_opportunity_history(hours=168)
    assert len(rows) == 1
    assert rows[0]["strategy_type"] == "binary_bid"


def test_build_strategy_backtest_aggregates(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa
    from quant_rd_tool import crypto_polymarket_backtest as bt

    monkeypatch.setattr(bt, "POLYMARKET_DIR", tmp_path)
    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    ts = datetime.now(UTC).isoformat()
    _write_opportunities(
        tmp_path / "opportunities.jsonl",
        [
            {
                "ts": ts,
                "opportunity": True,
                "strategy_type": "binary_ask",
                "condition_id": "c1",
                "edge_bps": 40,
                "edge_at_size_bps": 35,
                "profit_at_size_usd": 1.2,
                "fillable_shares": 120,
            },
            {
                "ts": ts,
                "opportunity": True,
                "strategy_type": "binary_ask",
                "condition_id": "c2",
                "edge_bps": 20,
                "edge_at_size_bps": 18,
                "profit_at_size_usd": 0.5,
                "fillable_shares": 80,
            },
        ],
    )
    pos_dir = tmp_path / "positions"
    pos_dir.mkdir()
    (pos_dir / "p1.json").write_text(
        json.dumps(
            {
                "id": "p1",
                "status": "closed",
                "cost_usd": 90,
                "fee_usd": 1,
                "realized_pnl_usd": 2,
            }
        ),
        encoding="utf-8",
    )

    report = build_strategy_backtest(hours=168)
    assert report["opportunity_hits"] == 2
    assert len(report["strategies"]) == 1
    assert report["strategies"][0]["hit_count"] == 2
    assert report["summary"]["closed_positions"] == 1
    assert report["summary"]["paper_win_rate"] == 1.0


def test_build_roi_distribution_buckets(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_backtest as bt

    monkeypatch.setattr(bt, "POLYMARKET_DIR", tmp_path)
    ts = datetime.now(UTC).isoformat()
    _write_opportunities(
        tmp_path / "opportunities.jsonl",
        [
            {"ts": ts, "opportunity": True, "edge_at_size_bps": 15, "strategy_type": "binary_ask"},
            {"ts": ts, "opportunity": True, "edge_at_size_bps": 55, "strategy_type": "binary_ask"},
        ],
    )
    dist = build_roi_distribution(hours=168)
    assert dist["n_opportunities"] == 2
    assert any(b["bucket"] == "0-20" for b in dist["edge_buckets"])


def test_build_advisor_calibration_empty(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_backtest as bt

    monkeypatch.setattr(bt, "POLYMARKET_DIR", tmp_path)
    (tmp_path / "positions").mkdir()
    report = build_advisor_calibration(hours=720)
    assert len(report["tiers"]) == 4
    assert report["sample_closed"] == 0


def test_calibration_report_cached(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_backtest as bt

    monkeypatch.setattr(bt, "POLYMARKET_DIR", tmp_path)
    (tmp_path / "positions").mkdir()
    bt._calibration_report_cache = None
    bt._calibration_report_key = None
    r1 = bt.get_advisor_calibration_report(hours=720)
    r2 = bt.get_advisor_calibration_report(hours=720)
    assert r1 is r2


def test_lookup_calibration_prior_requires_sample(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_backtest as bt

    monkeypatch.setattr(bt, "POLYMARKET_DIR", tmp_path)
    (tmp_path / "positions").mkdir()
    report = bt.build_advisor_calibration(hours=720)
    assert bt.lookup_calibration_prior(report, "strong_buy") is None
