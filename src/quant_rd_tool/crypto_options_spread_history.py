"""Local JSONL history for cross-venue aligned IV spreads."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def spread_history_dir(data_dir: str | Path = "data/crypto") -> Path:
    return Path(data_dir) / "options_iv_spread"


def spread_history_path(base: str, data_dir: str | Path = "data/crypto") -> Path:
    return spread_history_dir(data_dir) / f"{base.upper()}.jsonl"


def append_spread_snapshot(row: dict[str, Any], *, data_dir: str | Path = "data/crypto") -> Path:
    base = str(row.get("base") or "?").upper()
    path = spread_history_path(base, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def load_spread_history(
    base: str,
    *,
    data_dir: str | Path = "data/crypto",
    limit: int = 200,
) -> list[dict[str, Any]]:
    path = spread_history_path(base, data_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def snapshot_from_aligned(aligned: dict[str, Any]) -> dict[str, Any] | None:
    """Build a compact spread history row from aligned compare payload."""
    if not aligned.get("available"):
        return None
    cmp = aligned.get("comparison") or {}
    atm = aligned.get("atm") or {}
    return {
        "base": aligned.get("base"),
        "ts": now_iso(),
        "expiry_date": aligned.get("expiry_date"),
        "dte": aligned.get("dte"),
        "atm_strike": aligned.get("atm_strike"),
        "binance_iv": atm.get("binance_iv"),
        "deribit_iv": atm.get("deribit_iv"),
        "iv_spread_pp": cmp.get("iv_spread_pp"),
        "richer_venue": cmp.get("richer_venue"),
        "alert_level": cmp.get("alert_level"),
    }


def persist_aligned_spread(
    aligned: dict[str, Any],
    *,
    data_dir: str | Path = "data/crypto",
) -> Path | None:
    row = snapshot_from_aligned(aligned)
    if not row:
        return None
    return append_spread_snapshot(row, data_dir=data_dir)
