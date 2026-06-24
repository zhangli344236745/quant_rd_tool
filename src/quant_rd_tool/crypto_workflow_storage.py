"""Persist crypto workflow templates and run history."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = "data/crypto"


def workflow_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / "workflows"


def templates_path(data_dir: str | Path) -> Path:
    return workflow_root(data_dir) / "templates.json"


def runs_index_path(data_dir: str | Path) -> Path:
    return workflow_root(data_dir) / "runs.jsonl"


def run_dir(data_dir: str | Path, run_id: str) -> Path:
    return workflow_root(data_dir) / "runs" / run_id


def _default_template() -> dict[str, Any]:
    return {
        "id": "default-btc-1d",
        "name": "BTC 日线综合",
        "symbol_default": "BTC",
        "timeframe": "1d",
        "data_dir": DEFAULT_DATA_DIR,
        "steps": [
            {"id": "technical", "enabled": True, "order": 0, "params": {}},
            {"id": "qlib_ml", "enabled": True, "order": 1, "params": {"algorithm": "both"}},
            {
                "id": "zipline_strategy",
                "enabled": True,
                "order": 2,
                "params": {"strategy_id": "ma_crossover", "capital_base": 100_000},
            },
            {
                "id": "var_symbol",
                "enabled": True,
                "order": 3,
                "params": {
                    "notional_usdt": 10_000,
                    "lookback_bars": 252,
                    "horizon_days": 1,
                    "confidence": "0.95,0.99",
                },
            },
            {"id": "options_vol", "enabled": True, "order": 4, "params": {}},
            {"id": "advice_synth", "enabled": True, "order": 5, "params": {"var_gate_pct": 0.08}},
        ],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def list_templates(data_dir: str = DEFAULT_DATA_DIR) -> list[dict[str, Any]]:
    path = templates_path(data_dir)
    if not path.is_file():
        default = _default_template()
        save_templates(data_dir, [default])
        return [default]
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list) and raw:
        return raw
    default = _default_template()
    save_templates(data_dir, [default])
    return [default]


def save_templates(data_dir: str, templates: list[dict[str, Any]]) -> None:
    root = workflow_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    templates_path(data_dir).write_text(
        json.dumps(templates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_template(data_dir: str, template_id: str) -> dict[str, Any] | None:
    for t in list_templates(data_dir):
        if t.get("id") == template_id:
            return t
    return None


def upsert_template(data_dir: str, template: dict[str, Any]) -> dict[str, Any]:
    templates = list_templates(data_dir)
    tid = template.get("id") or str(uuid.uuid4())
    template["id"] = tid
    now = now_iso()
    template.setdefault("created_at", now)
    template["updated_at"] = now
    found = False
    for i, t in enumerate(templates):
        if t.get("id") == tid:
            templates[i] = template
            found = True
            break
    if not found:
        templates.append(template)
    save_templates(data_dir, templates)
    return template


def duplicate_template(data_dir: str, template_id: str, *, name: str | None = None) -> dict[str, Any] | None:
    src = get_template(data_dir, template_id)
    if not src:
        return None
    copy = {k: v for k, v in src.items() if k not in ("id", "created_at", "updated_at")}
    copy["id"] = str(uuid.uuid4())
    copy["name"] = name or f"{src.get('name', 'Workflow')} (副本)"
    return upsert_template(data_dir, copy)


def delete_template(data_dir: str, template_id: str) -> bool:
    templates = list_templates(data_dir)
    new_list = [t for t in templates if t.get("id") != template_id]
    if len(new_list) == len(templates):
        return False
    if not new_list:
        new_list = [_default_template()]
    save_templates(data_dir, new_list)
    return True


def save_run(data_dir: str, result: dict[str, Any]) -> dict[str, Any]:
    run_id = result.get("run_id") or str(uuid.uuid4())
    result["run_id"] = run_id
    result.setdefault("generated_at", now_iso())
    rd = run_dir(data_dir, run_id)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    index_row = {
        "run_id": run_id,
        "symbol": result.get("symbol"),
        "timeframe": result.get("timeframe"),
        "template_id": result.get("template_id"),
        "stance": (result.get("advice") or {}).get("stance"),
        "risk_level": (result.get("advice") or {}).get("risk_level"),
        "generated_at": result.get("generated_at"),
    }
    workflow_root(data_dir).mkdir(parents=True, exist_ok=True)
    with runs_index_path(data_dir).open("a", encoding="utf-8") as f:
        f.write(json.dumps(index_row, ensure_ascii=False) + "\n")
    return result


def list_runs(data_dir: str, *, limit: int = 20) -> list[dict[str, Any]]:
    path = runs_index_path(data_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    items: list[dict[str, Any]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        items.append(json.loads(line))
        if len(items) >= limit:
            break
    return items


def load_run(data_dir: str, run_id: str) -> dict[str, Any] | None:
    path = run_dir(data_dir, run_id) / "result.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
