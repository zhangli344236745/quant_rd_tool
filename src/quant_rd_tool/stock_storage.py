"""Local persistence for single-stock OHLCV and qlib bins."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_rd_tool.stock_codes import to_qlib_code


def stock_root(data_dir: str | Path, symbol: str) -> Path:
    code = to_qlib_code(symbol)
    return Path(data_dir).expanduser() / code


def csv_path(root: Path) -> Path:
    return root / "ohlcv.csv"


def qlib_path(root: Path) -> Path:
    return root / "qlib"


def meta_path(root: Path) -> Path:
    return root / "meta.json"


def report_json_path(root: Path) -> Path:
    return root / "report.json"


def report_md_path(root: Path) -> Path:
    return root / "report.md"


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False, encoding="utf-8")


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    if "symbol" not in df.columns and not df.empty:
        raise ValueError(f"Invalid CSV (missing symbol): {path}")
    return df.sort_values("date")


def save_qlib(df: pd.DataFrame, qlib_dir: Path) -> list[str]:
    from quant_rd_tool.qlib_dump import QlibDataDumper

    code = df["symbol"].iloc[0]
    return QlibDataDumper(qlib_dir).dump({code: df})


def write_meta(root: Path, payload: dict[str, Any]) -> None:
    payload = {**payload, "updated_at": now_iso()}
    meta_path(root).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_meta(root: Path) -> dict[str, Any]:
    p = meta_path(root)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
