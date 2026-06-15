"""Unified out-of-sample (OOS) protocol for qlib ML and walk-forward zipline strategies."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

PROTOCOL_VERSION = "1.0"

DEFAULT_GATES: dict[str, float | int] = {
    "min_test_ic": 0.02,
    "min_test_direction_accuracy": 0.52,
    "min_test_samples": 20,
    "min_valid_samples": 20,
}


def build_fixed_split_segments(
    start: str,
    end: str,
    *,
    train_ratio: float = 0.6,
    valid_ratio: float = 0.2,
    min_span_days: int = 365,
    intraday: bool = False,
) -> dict[str, tuple[str, str]]:
    """Chronological train / valid / test segments (no shuffle)."""
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    span = (e - s).days
    if span < min_span_days:
        raise ValueError(
            f"OOS fixed split needs ~{min_span_days} days; got {span} days ({start} → {end})."
        )
    t1 = s + pd.Timedelta(days=int(span * train_ratio))
    t2 = s + pd.Timedelta(days=int(span * (train_ratio + valid_ratio)))

    def _fmt(ts: pd.Timestamp) -> str:
        if intraday:
            return ts.strftime("%Y-%m-%d %H:%M:%S")
        return ts.strftime("%Y-%m-%d")

    return {
        "train": (_fmt(s), _fmt(t1)),
        "valid": (_fmt(t1 + pd.Timedelta(days=1)), _fmt(t2)),
        "test": (_fmt(t2 + pd.Timedelta(days=1)), _fmt(e)),
    }


def metrics_from_pairs(preds: list[float], labels: list[float]) -> dict[str, float | int | None]:
    if len(preds) < 10:
        return {"samples": len(preds)}
    frame = pd.DataFrame({"pred": preds, "label": labels}).dropna()
    if len(frame) < 10:
        return {"samples": int(len(frame))}
    ic = float(frame["pred"].corr(frame["label"]))
    rank_ic = float(frame["pred"].corr(frame["label"], method="spearman"))
    direction = float((np.sign(frame["pred"]) == np.sign(frame["label"])).mean())
    mse = float(((frame["pred"] - frame["label"]) ** 2).mean())
    return {
        "samples": int(len(frame)),
        "ic": round(ic, 6) if pd.notna(ic) else None,
        "rank_ic": round(rank_ic, 6) if pd.notna(rank_ic) else None,
        "direction_accuracy": round(direction, 4),
        "mse": round(mse, 8),
    }


def evaluate_oos_gate(
    report: dict[str, Any],
    *,
    gates: dict[str, float | int] | None = None,
) -> dict[str, Any]:
    g = {**DEFAULT_GATES, **(gates or {})}
    test = report.get("test_metrics") or {}
    valid = report.get("valid_metrics") or {}
    reasons: list[str] = []
    passed = True

    n_test = int(test.get("samples") or 0)
    if n_test < int(g["min_test_samples"]):
        passed = False
        reasons.append(f"测试样本不足 ({n_test} < {g['min_test_samples']})")

    n_valid = int(valid.get("samples") or 0)
    if report.get("protocol_type") != "walk_forward":
        if n_valid < int(g["min_valid_samples"]):
            passed = False
            reasons.append(f"验证样本不足 ({n_valid} < {g['min_valid_samples']})")

    ic = test.get("ic")
    if ic is not None and ic < float(g["min_test_ic"]):
        passed = False
        reasons.append(f"测试 IC {ic:.4f} < {g['min_test_ic']}")

    acc = test.get("direction_accuracy")
    if acc is not None and acc < float(g["min_test_direction_accuracy"]):
        passed = False
        reasons.append(f"方向命中率 {acc:.2%} < {g['min_test_direction_accuracy']:.0%}")

    return {
        "passed": passed,
        "reasons": reasons,
        "thresholds": g,
    }


def build_fixed_split_report(
    *,
    segments: dict[str, tuple[str, str]],
    segment_counts: dict[str, int] | None = None,
    valid_metrics: dict[str, Any] | None = None,
    test_metrics: dict[str, Any] | None = None,
    train_metrics: dict[str, Any] | None = None,
    algorithm: str = "ml",
    instrument: str | None = None,
) -> dict[str, Any]:
    valid_metrics = valid_metrics or {}
    test_metrics = test_metrics or {}
    combined_samples = int(valid_metrics.get("samples") or 0) + int(test_metrics.get("samples") or 0)
    report: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_type": "fixed_split",
        "algorithm": algorithm,
        "instrument": instrument,
        "segments": segments,
        "segment_counts": segment_counts or {},
        "oos_scope": "valid+test",
        "train_metrics": train_metrics or {},
        "valid_metrics": valid_metrics,
        "test_metrics": test_metrics,
        "combined_oos_samples": combined_samples,
    }
    report["gate"] = evaluate_oos_gate(report)
    report["headline"] = _headline_fixed_split(report)
    report["markdown"] = render_oos_markdown(report)
    return report


def build_walk_forward_report(
    *,
    timeframe: str,
    params: dict[str, Any],
    oos_metrics: dict[str, Any],
    n_oos_bars: int,
    n_retrains: int,
    algorithm: str = "walk_forward_xgb",
    instrument: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_type": "walk_forward",
        "algorithm": algorithm,
        "instrument": instrument,
        "timeframe": timeframe,
        "params": {
            "train_bars": params.get("train_bars"),
            "retrain_every": params.get("retrain_every"),
            "label_horizon": params.get("label_horizon"),
            "min_train_samples": params.get("min_train_samples"),
        },
        "oos_scope": "post_train_window",
        "n_oos_bars": n_oos_bars,
        "n_retrains": n_retrains,
        "valid_metrics": {},
        "test_metrics": oos_metrics,
        "combined_oos_samples": int(oos_metrics.get("samples") or 0),
    }
    report["gate"] = evaluate_oos_gate(report)
    report["headline"] = _headline_walk_forward(report)
    report["markdown"] = render_oos_markdown(report)
    return report


def _headline_fixed_split(report: dict[str, Any]) -> str:
    tm = report.get("test_metrics") or {}
    gate = report.get("gate") or {}
    status = "通过" if gate.get("passed") else "未通过"
    ic = tm.get("ic")
    acc = tm.get("direction_accuracy")
    ic_s = f"{ic:.4f}" if ic is not None else "—"
    acc_s = f"{acc:.1%}" if acc is not None else "—"
    return f"固定切分 OOS · 测试 IC={ic_s} · 命中={acc_s} · {status}"


def _headline_walk_forward(report: dict[str, Any]) -> str:
    tm = report.get("test_metrics") or {}
    gate = report.get("gate") or {}
    status = "通过" if gate.get("passed") else "未通过"
    ic = tm.get("ic")
    ic_s = f"{ic:.4f}" if ic is not None else "—"
    return f"Walk-forward OOS · IC={ic_s} · {report.get('n_oos_bars', 0)} bars · {status}"


def render_oos_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"## OOS 协议 ({report.get('protocol_type')})",
        "",
        f"- 版本: {report.get('protocol_version')}",
        f"- 范围: {report.get('oos_scope')}",
    ]
    if report.get("protocol_type") == "fixed_split":
        segs = report.get("segments") or {}
        for name in ("train", "valid", "test"):
            if name in segs:
                a, b = segs[name]
                cnt = (report.get("segment_counts") or {}).get(name)
                extra = f" ({cnt} rows)" if cnt is not None else ""
                lines.append(f"- {name}: {a} → {b}{extra}")
    else:
        p = report.get("params") or {}
        lines.append(f"- train_bars: {p.get('train_bars')}")
        lines.append(f"- retrain_every: {p.get('retrain_every')}")
        lines.append(f"- OOS bars: {report.get('n_oos_bars')}")
        lines.append(f"- 重训次数: {report.get('n_retrains')}")

    tm = report.get("test_metrics") or {}
    lines.extend(
        [
            "",
            "### 测试集 / OOS 指标",
            f"- IC: {tm.get('ic', '—')}",
            f"- Rank IC: {tm.get('rank_ic', '—')}",
            f"- 方向命中率: {tm.get('direction_accuracy', '—')}",
            f"- 样本数: {tm.get('samples', '—')}",
        ]
    )
    gate = report.get("gate") or {}
    lines.extend(["", f"### 门控: {'✅ 通过' if gate.get('passed') else '❌ 未通过'}"])
    for r in gate.get("reasons") or []:
        lines.append(f"- {r}")
    lines.extend(
        [
            "",
            "_说明：OOS 区间未参与模型选择；门控仅作研究质量参考，不构成投资建议。_",
        ]
    )
    return "\n".join(lines)


def summarize_panel_oos(per_item: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate OOS reports across a universe (e.g. Top-K ML panel)."""
    passed = 0
    total = 0
    ics: list[float] = []
    for _code, item in per_item.items():
        proto = item.get("oos_protocol")
        if not proto:
            continue
        total += 1
        if (proto.get("gate") or {}).get("passed"):
            passed += 1
        ic = (proto.get("test_metrics") or {}).get("ic")
        if ic is not None:
            ics.append(float(ic))
    return {
        "instruments_with_oos": total,
        "gate_pass_count": passed,
        "gate_pass_rate": round(passed / total, 4) if total else None,
        "mean_test_ic": round(float(np.mean(ics)), 6) if ics else None,
    }


def compact_oos_for_ui(oos_protocol: dict[str, Any] | None) -> dict[str, Any] | None:
    """Lightweight OOS block for workflow steps and API summaries."""
    if not oos_protocol:
        return None
    gate = oos_protocol.get("gate") or {}
    test = oos_protocol.get("test_metrics") or oos_protocol.get("oos_metrics") or {}
    return {
        "protocol_type": oos_protocol.get("protocol_type"),
        "protocol_version": oos_protocol.get("protocol_version"),
        "gate_passed": gate.get("passed"),
        "gate_reasons": gate.get("reasons") or [],
        "test_ic": test.get("ic"),
        "direction_accuracy": test.get("direction_accuracy"),
        "test_samples": test.get("samples"),
        "headline": oos_protocol.get("headline"),
        "markdown": oos_protocol.get("markdown"),
    }
