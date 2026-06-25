"""Polymarket edge history, trends, and leaderboards."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from quant_rd_tool.time_util import now_iso


def _poly_dir():
    from quant_rd_tool.crypto_polymarket_arb import POLYMARKET_DIR

    return POLYMARKET_DIR


def _edge_history_path():
    return _poly_dir() / "edge_history.jsonl"


def _ensure_dirs() -> None:
    _poly_dir().mkdir(parents=True, exist_ok=True)


def append_edge_history(row: dict[str, Any]) -> None:
    if not row.get("opportunity"):
        return
    _ensure_dirs()
    doc = {
        "ts": now_iso(),
        "condition_id": row.get("condition_id"),
        "question": row.get("question"),
        "strategy_type": row.get("strategy_type"),
        "edge_bps": row.get("edge_bps"),
        "edge_at_size_bps": row.get("edge_at_size_bps"),
        "profit_at_size_usd": row.get("profit_at_size_usd"),
    }
    with _edge_history_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")


def _read_history_lines() -> list[dict[str, Any]]:
    path = _edge_history_path()
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def edge_trend(
    condition_id: str,
    *,
    hours: float = 24.0,
    strategy_type: str | None = None,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    items: list[dict[str, Any]] = []
    for doc in _read_history_lines():
        if str(doc.get("condition_id") or "") != condition_id:
            continue
        if strategy_type and doc.get("strategy_type") != strategy_type:
            continue
        ts = _parse_ts(str(doc.get("ts") or ""))
        if ts is None or ts < cutoff:
            continue
        items.append(doc)
    items.sort(key=lambda r: str(r.get("ts") or ""))
    return items


def leaderboard(
    *,
    hours: float = 168.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    by_cid: dict[str, dict[str, Any]] = {}
    for doc in _read_history_lines():
        ts = _parse_ts(str(doc.get("ts") or ""))
        if ts is None or ts < cutoff:
            continue
        cid = str(doc.get("condition_id") or "")
        if not cid:
            continue
        agg = by_cid.setdefault(
            cid,
            {
                "condition_id": cid,
                "question": doc.get("question"),
                "hit_count": 0,
                "best_edge_bps": None,
                "best_edge_at_size_bps": None,
                "last_ts": doc.get("ts"),
                "strategies": set(),
            },
        )
        agg["hit_count"] += 1
        agg["strategies"].add(doc.get("strategy_type"))
        be = doc.get("edge_bps")
        if be is not None and (agg["best_edge_bps"] is None or float(be) > float(agg["best_edge_bps"])):
            agg["best_edge_bps"] = be
        bes = doc.get("edge_at_size_bps")
        if bes is not None and (
            agg["best_edge_at_size_bps"] is None
            or float(bes) > float(agg["best_edge_at_size_bps"])
        ):
            agg["best_edge_at_size_bps"] = bes
        if str(doc.get("ts") or "") > str(agg.get("last_ts") or ""):
            agg["last_ts"] = doc.get("ts")
            agg["question"] = doc.get("question")

    rows = list(by_cid.values())
    for r in rows:
        r["strategies"] = sorted(s for s in r["strategies"] if s)
    rows.sort(
        key=lambda r: (
            int(r.get("hit_count") or 0),
            float(r.get("best_edge_at_size_bps") or r.get("best_edge_bps") or -1e9),
        ),
        reverse=True,
    )
    return rows[:limit]
