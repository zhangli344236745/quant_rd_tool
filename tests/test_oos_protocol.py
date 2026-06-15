"""Tests for unified OOS protocol."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_rd_tool.crypto_zipline_ml import compute_walk_forward_targets
from quant_rd_tool.oos_protocol import (
    build_fixed_split_report,
    build_fixed_split_segments,
    metrics_from_pairs,
    summarize_panel_oos,
)


def test_fixed_split_segments_order():
    segs = build_fixed_split_segments("2020-01-01", "2022-01-01", min_span_days=365)
    assert segs["train"][0] == "2020-01-01"
    assert segs["train"][1] < segs["valid"][0]
    assert segs["valid"][1] < segs["test"][0]


def test_oos_gate_pass():
    report = build_fixed_split_report(
        segments=build_fixed_split_segments("2020-01-01", "2022-06-01"),
        valid_metrics={"samples": 50, "ic": 0.05, "direction_accuracy": 0.55},
        test_metrics={"samples": 50, "ic": 0.04, "direction_accuracy": 0.54},
        algorithm="xgb",
        instrument="SH600519",
    )
    assert report["gate"]["passed"] is True
    assert "markdown" in report
    assert report["protocol_type"] == "fixed_split"


def test_oos_gate_fail_low_ic():
    report = build_fixed_split_report(
        segments=build_fixed_split_segments("2020-01-01", "2022-06-01"),
        valid_metrics={"samples": 50, "ic": 0.01, "direction_accuracy": 0.5},
        test_metrics={"samples": 50, "ic": 0.005, "direction_accuracy": 0.48},
    )
    assert report["gate"]["passed"] is False
    assert report["gate"]["reasons"]


def test_metrics_from_pairs():
    preds = [0.01, -0.02, 0.03, -0.01] * 10
    labels = [0.008, -0.015, 0.025, -0.008] * 10
    m = metrics_from_pairs(preds, labels)
    assert m["samples"] >= 40
    assert m.get("ic") is not None


def test_walk_forward_includes_oos_protocol():
    rng = np.random.default_rng(0)
    n = 900
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": rng.uniform(100, 1000, n),
        }
    )
    params = {"train_bars": 300, "retrain_every": 150, "min_train_samples": 80}
    _, metrics = compute_walk_forward_targets(df, params, timeframe="1d", include_tv=False)
    assert "oos_protocol" in metrics
    assert metrics["oos_protocol"]["protocol_type"] == "walk_forward"
    assert "gate" in metrics["oos_protocol"]


def test_summarize_panel_oos():
    panel = {
        "SH600519": {
            "oos_protocol": build_fixed_split_report(
                segments=build_fixed_split_segments("2020-01-01", "2022-06-01"),
                valid_metrics={"samples": 40, "ic": 0.03, "direction_accuracy": 0.53},
                test_metrics={"samples": 40, "ic": 0.03, "direction_accuracy": 0.53},
            )
        }
    }
    summary = summarize_panel_oos(panel)
    assert summary["instruments_with_oos"] == 1
    assert summary["gate_pass_count"] == 1
