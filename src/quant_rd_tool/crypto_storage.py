"""Local crypto OHLCV storage with incremental merge and metadata."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_time import (
    BEIJING_TZ,
    ms_to_beijing_str,
    normalize_ohlcv_dates,
    utc_now_beijing_str,
)

OHLCV_COLUMNS = ["timestamp", "date", "symbol", "open", "high", "low", "close", "volume"]
DISPLAY_TZ = BEIJING_TZ


def ohlcv_csv_path(root: Path, timeframe: str) -> Path:
    if timeframe in ("1d", "1D", "day"):
        return root / "ohlcv.csv"
    safe = timeframe.replace("/", "")
    return root / f"ohlcv_{safe}.csv"


def meta_path(root: Path, timeframe: str) -> Path:
    safe = timeframe.replace("/", "")
    return root / f"meta_{safe}.json"


def qlib_dir_for(root: Path, timeframe: str) -> Path:
    if timeframe in ("1d", "1D", "day"):
        return root / "qlib"
    safe = timeframe.replace("/", "")
    return root / f"qlib_{safe}"


def load_meta(root: Path, timeframe: str) -> dict[str, Any] | None:
    path = meta_path(root, timeframe)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_meta(root: Path, timeframe: str, meta: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    meta_path(root, timeframe).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_ohlcv_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return normalize_ohlcv_dates(pd.read_csv(path))


def row_timestamp_ms(row: pd.Series) -> int:
    if "timestamp" in row.index and pd.notna(row["timestamp"]):
        return int(row["timestamp"])
    return int(pd.Timestamp(row["date"]).tz_localize(BEIJING_TZ).timestamp() * 1000)


def merge_ohlcv(existing: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        out = normalize_ohlcv_dates(new)
    else:
        out = normalize_ohlcv_dates(pd.concat([existing, new], ignore_index=True))
    out = out.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
    return out.reset_index(drop=True)


def save_ohlcv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def sync_ohlcv(
    symbol: str,
    *,
    data_dir: str | Path,
    timeframe: str = "5m",
    backfill_days: int = 90,
    exchange_id: cxt.ExchangeId = "binance",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Incrementally fetch Binance OHLCV via ccxt and merge into local CSV.

    First run backfills ``backfill_days`` of history; later runs append only new bars.
    """
    root = Path(data_dir) / cxt.to_qlib_code(symbol)
    root.mkdir(parents=True, exist_ok=True)
    csv_file = ohlcv_csv_path(root, timeframe)
    meta = load_meta(root, timeframe)
    existing = load_ohlcv_csv(csv_file)

    if existing is None or existing.empty:
        since_ms = int((datetime.now(UTC).timestamp() - backfill_days * 86400) * 1000)
        new_df = cxt.fetch_ohlcv_history(
            symbol,
            timeframe=timeframe,
            since_ms=since_ms,
            exchange_id=exchange_id,
        )
        merged = merge_ohlcv(None, new_df)
        action = "backfill"
    else:
        last_ts = meta.get("last_timestamp_ms") if meta else None
        if last_ts is None:
            last_ts = row_timestamp_ms(existing.iloc[-1])
        new_df = cxt.fetch_ohlcv_incremental(
            symbol,
            timeframe=timeframe,
            last_timestamp_ms=int(last_ts),
            exchange_id=exchange_id,
        )
        merged = merge_ohlcv(existing, new_df)
        action = "incremental" if len(new_df) else "noop"

    save_ohlcv(merged, csv_file)
    last_row = merged.iloc[-1]
    last_timestamp_ms = row_timestamp_ms(last_row)
    last_utc = datetime.fromtimestamp(last_timestamp_ms / 1000, tz=UTC)
    now_utc = datetime.now(UTC)
    lag_minutes = max(int((now_utc - last_utc).total_seconds() // 60), 0)
    bar_minutes = max(cxt.timeframe_to_ms(timeframe) // 60_000, 1)
    bar_close_utc = last_utc.timestamp() + bar_minutes * 60
    last_bar_closed = now_utc.timestamp() >= bar_close_utc
    last_bj = ms_to_beijing_str(last_timestamp_ms)
    bar_close_bj = datetime.fromtimestamp(bar_close_utc, tz=UTC).astimezone(BEIJING_TZ)
    updated_meta = {
        "symbol": symbol,
        "qlib_code": cxt.to_qlib_code(symbol),
        "pair": cxt.to_ccxt_symbol(symbol),
        "timeframe": timeframe,
        "bars_count": len(merged),
        "last_timestamp_ms": last_timestamp_ms,
        "last_date": last_bj,
        "last_date_beijing": last_bj,
        "last_date_utc": last_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "last_date_local": last_bj,
        "date_timezone": "Asia/Shanghai",
        "timezone_note": "CSV 列 date 与 last_date 均为北京时间 (UTC+8)；timestamp 列为 UTC 毫秒",
        "data_lag_minutes": lag_minutes,
        "last_bar_closed": last_bar_closed,
        "expected_lag_note": (
            f"最后一根 K 线北京时间开盘 {last_bj}，"
            f"理论收盘 {bar_close_bj.strftime('%Y-%m-%d %H:%M:%S')}；"
            f"{'已收盘' if last_bar_closed else '未收盘（当前正在形成的 K 线）'}。"
            f"与当前相差约 {lag_minutes} 分钟；超过 {bar_minutes} 分钟请重新 sync。"
        ),
        "last_close": float(last_row["close"]),
        "updated_at": now_utc.isoformat(),
        "updated_at_beijing": utc_now_beijing_str(),
        "last_sync_action": action,
        "new_bars": len(new_df) if action != "noop" else 0,
    }
    save_meta(root, timeframe, updated_meta)
    return merged, updated_meta
