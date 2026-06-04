"""Persist zipline lab backtest runs."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DISCLAIMER = "回测结果仅供参考，不构成投资建议。"


def lab_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / "zipline" / "lab"


def runs_index_path(data_dir: str | Path) -> Path:
    return lab_root(data_dir) / "runs.jsonl"


def run_dir(data_dir: str | Path, run_id: str) -> Path:
    return lab_root(data_dir) / run_id


def append_run_index(data_dir: str | Path, summary: dict[str, Any]) -> None:
    root = lab_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    with runs_index_path(data_dir).open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


def save_run(data_dir: str | Path, result: dict[str, Any]) -> dict[str, Any]:
    run_id = result.get("run_id") or str(uuid.uuid4())
    result["run_id"] = run_id
    result.setdefault("disclaimer", DISCLAIMER)
    result.setdefault("generated_at", datetime.now(UTC).isoformat())

    rd = run_dir(data_dir, run_id)
    rd.mkdir(parents=True, exist_ok=True)
    params = {k: result.get(k) for k in ("symbol", "strategy", "timeframe", "start", "end", "capital_base", "engine", "strategy_params")}
    (rd / "params.json").write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

    trades = result.pop("trades", [])
    equity = result.pop("equity_curve", [])
    payload = dict(result)
    payload["trade_count"] = len(trades)
    (rd / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with (rd / "trades.jsonl").open("w", encoding="utf-8") as f:
        for t in trades:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    (rd / "equity_curve.json").write_text(json.dumps(equity, ensure_ascii=False), encoding="utf-8")

    result["trades"] = trades
    result["equity_curve"] = equity

    index_row = {
        "run_id": run_id,
        "symbol": result.get("symbol"),
        "strategy": result.get("strategy"),
        "engine": result.get("engine"),
        "start": result.get("start"),
        "end": result.get("end"),
        "total_return": (result.get("metrics") or {}).get("total_return"),
        "generated_at": result.get("generated_at"),
    }
    append_run_index(data_dir, index_row)
    return result


def list_runs(data_dir: str | Path, *, limit: int = 20) -> list[dict[str, Any]]:
    path = runs_index_path(data_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    items: list[dict[str, Any]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(items) >= limit:
            break
    return items


def load_run(data_dir: str | Path, run_id: str) -> dict[str, Any] | None:
    rd = run_dir(data_dir, run_id)
    result_path = rd / "result.json"
    if not result_path.is_file():
        return None
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    eq_path = rd / "equity_curve.json"
    if eq_path.is_file():
        try:
            result["equity_curve"] = json.loads(eq_path.read_text(encoding="utf-8"))
        except Exception:
            result["equity_curve"] = []
    trades_path = rd / "trades.jsonl"
    if trades_path.is_file():
        trades = []
        for line in trades_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        result["trades"] = trades
    return result
