from __future__ import annotations

from quant_rd_tool.crypto_polymarket_advisor import (
    AdvisorConfig,
    build_recommendations,
    classify_recommendation,
    estimate_win_rate,
    execution_confidence,
    profit_analysis,
    score_opportunity,
)


def test_execution_confidence_full_fill():
    row = {"fillable_shares": 100, "slippage_bps": 2, "depth_levels": 3}
    assert execution_confidence(row, 100) >= 0.9


def test_estimate_win_rate_binary_ask():
    row = {
        "condition_id": "c1",
        "strategy_type": "binary_ask",
        "fillable_shares": 100,
        "slippage_bps": 1,
        "depth_levels": 2,
        "opportunity": True,
        "edge_at_size": 0.02,
        "edge_at_size_bps": 200,
        "ask_yes": 0.45,
        "ask_no": 0.50,
        "profit_at_size_usd": 2.0,
    }
    win = estimate_win_rate(row, history_hours=168, target_shares=100)
    assert win["win_rate"] >= 0.6
    assert win["strategy_certainty"] == 0.98


def test_classify_strong_buy():
    cfg = AdvisorConfig()
    win_rate = 0.80
    profit = {"net_profit_usd": 1.5}
    row = {"opportunity": True, "paper_tradable": True}
    assert classify_recommendation(win_rate, profit, row, cfg) == "strong_buy"


def test_profit_analysis_binary_ask():
    row = {
        "strategy_type": "binary_ask",
        "vwap_yes": 0.45,
        "vwap_no": 0.50,
        "fillable_shares": 100,
        "edge_at_size": 0.02,
        "profit_at_size_usd": 2.0,
    }
    p = profit_analysis(row, target_shares=100, taker_fee_bps=200)
    assert p["recommended_size_shares"] == 100
    assert p["expected_profit_usd"] > 0
    assert p["roi_pct"] > 0


def test_score_opportunity_has_advice():
    row = {
        "condition_id": "c1",
        "question": "Test market?",
        "strategy_type": "binary_ask",
        "opportunity": True,
        "paper_tradable": True,
        "fillable_shares": 100,
        "slippage_bps": 1,
        "depth_levels": 2,
        "edge_at_size": 0.03,
        "edge_at_size_bps": 300,
        "vwap_yes": 0.44,
        "vwap_no": 0.50,
        "profit_at_size_usd": 3.0,
    }
    scored = score_opportunity(row)
    assert scored["recommendation"] in ("strong_buy", "buy", "watch")
    assert "advice" in scored
    assert scored["win_rate_pct"] > 0


def test_build_recommendations_from_scan():
    scan = {
        "scanned_at": "2026-06-25T12:00:00+08:00",
        "items": [
            {
                "condition_id": "c1",
                "question": "A?",
                "strategy_type": "binary_ask",
                "opportunity": True,
                "paper_tradable": True,
                "fillable_shares": 100,
                "slippage_bps": 0,
                "depth_levels": 2,
                "edge_at_size_bps": 250,
                "edge_at_size": 0.025,
                "vwap_yes": 0.43,
                "vwap_no": 0.50,
                "profit_at_size_usd": 2.5,
            },
            {
                "condition_id": "c2",
                "question": "B?",
                "strategy_type": "binary_bid",
                "opportunity": True,
                "paper_tradable": False,
                "fillable_shares": 50,
                "slippage_bps": 10,
                "depth_levels": 1,
                "edge_at_size_bps": 80,
                "bid_yes": 0.55,
                "bid_no": 0.50,
                "profit_at_size_usd": 0.5,
            },
        ],
    }
    report = build_recommendations(scan, min_win_rate=0.5, limit=5)
    assert report["total_opportunities"] == 2
    assert len(report["top_picks"]) >= 1
    assert report["top_picks"][0]["score"] >= report["top_picks"][-1]["score"]


def test_estimate_win_rate_uses_spec_weights_with_calibration():
    row = {
        "condition_id": "c1",
        "strategy_type": "binary_ask",
        "fillable_shares": 100,
        "slippage_bps": 1,
        "depth_levels": 2,
    }
    base = estimate_win_rate(row, history_hours=168, target_shares=100)
    calibrated = estimate_win_rate(row, history_hours=168, target_shares=100, calibrated_wr=0.9)
    assert calibrated["win_rate"] != base["win_rate"]
    assert calibrated["calibrated_prior"] == 0.9
