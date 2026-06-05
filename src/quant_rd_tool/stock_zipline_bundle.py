"""A-share OHLCV → zipline-reloaded csvdir daily bundle (XSHG calendar)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_rd_tool.stock_codes import to_qlib_code
from quant_rd_tool.stock_storage import csv_path, load_csv, stock_root
from quant_rd_tool.stock_zipline_timeframes import (
    DEFAULT_TIMEFRAME,
    bar_minutes_for,
    bundle_name_for,
    normalize_timeframe,
)

logger = logging.getLogger(__name__)

TIMEFRAME = DEFAULT_TIMEFRAME
_BUNDLE_REGISTERED: set[str] = set()
_CALENDAR = None


def zipline_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / "zipline"


def bundle_csvdir(data_dir: str | Path, timeframe: str = TIMEFRAME) -> Path:
    tf = normalize_timeframe(timeframe)
    return zipline_root(data_dir) / "bundles" / f"stock_csvdir_{tf}"


def zipline_import_ok() -> tuple[bool, str | None]:
    try:
        import zipline  # noqa: F401
        from zipline.utils.run_algo import run_algorithm  # noqa: F401

        return True, None
    except Exception as exc:
        return False, str(exc)


def zipline_available() -> tuple[bool, str | None]:
    from quant_rd_tool.crypto_zipline_env import zipline_venv_ready

    return zipline_venv_ready()


def get_stock_calendar():
    global _CALENDAR
    if _CALENDAR is None:
        from exchange_calendars import get_calendar

        _CALENDAR = get_calendar("XSHG")
    return _CALENDAR


def load_ohlcv_window(
    symbol: str,
    *,
    data_dir: str | Path,
    timeframe: str = TIMEFRAME,
    lookback_days: int = 365,
    range_start: str | None = None,
    range_end: str | None = None,
) -> pd.DataFrame:
    tf = normalize_timeframe(timeframe)
    root = stock_root(data_dir, symbol)
    path = csv_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"No daily data for {symbol}; sync first")
    df = load_csv(path)
    if df.empty:
        raise ValueError(f"Empty OHLCV for {symbol}")

    ts = pd.to_datetime(df["date"])
    df = df.copy()
    df["_ts"] = ts
    cutoff = datetime.now(UTC) - pd.Timedelta(days=lookback_days)
    if range_start:
        rs = pd.Timestamp(range_start) - pd.Timedelta(days=5)
        cutoff = min(cutoff, rs.to_pydatetime().replace(tzinfo=UTC))
    df = df[df["_ts"] >= pd.Timestamp(cutoff).tz_localize(None)]
    if range_end:
        re = pd.Timestamp(range_end) + pd.Timedelta(days=1)
        df = df[df["_ts"] <= re]
    df = df.drop(columns=["_ts"])
    if df.empty:
        raise ValueError(f"Not enough daily bars for {symbol} in requested window")
    return df.reset_index(drop=True)


def data_status(symbol: str, *, data_dir: str | Path, timeframe: str = TIMEFRAME) -> dict[str, Any]:
    tf = normalize_timeframe(timeframe)
    code = to_qlib_code(symbol)
    root = stock_root(data_dir, symbol)
    path = csv_path(root)
    if not path.is_file():
        return {"symbol": code, "timeframe": tf, "ready": False, "bars_count": 0}
    df = load_csv(path)
    count = len(df)
    last_date = str(df.iloc[-1]["date"]) if count else None
    return {
        "symbol": code,
        "timeframe": tf,
        "ready": count > 0,
        "bars_count": count,
        "last_bar": last_date,
        "path": str(path),
    }


def write_csvdir_daily(df: pd.DataFrame, asset_name: str, *, csvdir: Path) -> Path:
    daily_dir = csvdir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    dt = pd.to_datetime(out["date"])
    out["date"] = dt.dt.strftime("%Y-%m-%d")
    out_path = daily_dir / f"{asset_name}.csv"
    cols = ["date", "open", "high", "low", "close", "volume"]
    if "amount" in out.columns:
        cols.append("amount")
    out[cols].to_csv(out_path, index=False)
    return out_path


def prepare_csvdir(
    symbol: str,
    df: pd.DataFrame,
    *,
    data_dir: str | Path,
    timeframe: str = TIMEFRAME,
) -> Path:
    asset = to_qlib_code(symbol)
    out_csvdir = bundle_csvdir(data_dir, timeframe)
    if out_csvdir.exists():
        shutil.rmtree(out_csvdir)
    write_csvdir_daily(df, asset, csvdir=out_csvdir)
    return out_csvdir


def configure_zipline_env(data_dir: str | Path) -> Path:
    root = zipline_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    os.environ["ZIPLINE_ROOT"] = str(root.resolve())
    return root


def _register_bundle(
    csvdir: Path,
    *,
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> str:
    from zipline.data.bundles import register
    from zipline.data.bundles.csvdir import csvdir_equities

    name = bundle_name_for(timeframe)
    if name in _BUNDLE_REGISTERED:
        return name
    get_stock_calendar()
    register(
        name,
        csvdir_equities(["daily"], str(csvdir)),
        calendar_name="XSHG",
        start_session=start,
        end_session=end,
    )
    _BUNDLE_REGISTERED.add(name)
    return name


def bundle_manifest_path(data_dir: str | Path) -> Path:
    return zipline_root(data_dir) / "bundle_manifest.json"


def df_fingerprint(
    symbol: str,
    df: pd.DataFrame,
    *,
    timeframe: str,
    ingest_start: pd.Timestamp,
    ingest_end: pd.Timestamp,
) -> str:
    first = str(df.iloc[0].get("date"))
    last = str(df.iloc[-1].get("date"))
    close_sum = round(float(df["close"].sum()), 4)
    tf = normalize_timeframe(timeframe)
    payload = f"stock|{symbol}|{tf}|{len(df)}|{first}|{last}|{close_sum}|{ingest_start}|{ingest_end}"
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def read_bundle_manifest(data_dir: str | Path) -> dict[str, Any]:
    path = bundle_manifest_path(data_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_bundle_manifest(data_dir: str | Path, manifest: dict[str, Any]) -> None:
    path = bundle_manifest_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def bundle_data_exists(data_dir: str | Path, timeframe: str = TIMEFRAME) -> bool:
    name = bundle_name_for(timeframe)
    bundle_dir = zipline_root(data_dir) / "data" / name
    if not bundle_dir.is_dir():
        return False
    return any(bundle_dir.iterdir())


def ensure_bundle_ingested(
    symbol: str,
    df: pd.DataFrame,
    *,
    data_dir: str | Path,
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    force: bool = False,
) -> dict[str, Any]:
    tf = normalize_timeframe(timeframe)
    fp = df_fingerprint(symbol, df, timeframe=tf, ingest_start=start, ingest_end=end)
    manifest = read_bundle_manifest(data_dir)
    cached = (
        manifest.get("fingerprint") == fp
        and manifest.get("timeframe") == tf
        and bundle_data_exists(data_dir, tf)
    )
    if cached and not force:
        configure_zipline_env(data_dir)
        csvdir = bundle_csvdir(data_dir, tf)
        _register_bundle(csvdir, timeframe=tf, start=start, end=end)
        return {
            "ingest_skipped": True,
            "fingerprint": fp,
            "bars": len(df),
            "timeframe": tf,
            "bundle": bundle_name_for(tf),
        }

    ingest_bundle_for_symbol(symbol, df, data_dir=data_dir, timeframe=tf, start=start, end=end)
    write_bundle_manifest(
        data_dir,
        {
            "fingerprint": fp,
            "symbol": symbol,
            "timeframe": tf,
            "bars": len(df),
            "bar_minutes": bar_minutes_for(tf),
            "ingest_start": str(start),
            "ingest_end": str(end),
            "ingested_at": datetime.now(UTC).isoformat(),
            "bundle": bundle_name_for(tf),
            "market": "stock",
        },
    )
    return {
        "ingest_skipped": False,
        "fingerprint": fp,
        "bars": len(df),
        "timeframe": tf,
        "bundle": bundle_name_for(tf),
    }


def ingest_bundle_for_symbol(
    symbol: str,
    df: pd.DataFrame,
    *,
    data_dir: str | Path,
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> str:
    ok, err = zipline_import_ok()
    if not ok:
        raise RuntimeError(f"zipline-reloaded not importable: {err}")

    from zipline.data.bundles import ingest

    tf = normalize_timeframe(timeframe)
    name = bundle_name_for(tf)
    configure_zipline_env(data_dir)
    csvdir = prepare_csvdir(symbol, df, data_dir=data_dir, timeframe=tf)
    _register_bundle(csvdir, timeframe=tf, start=start, end=end)
    logger.info("Ingesting stock zipline bundle %s (%d daily bars)", name, len(df))
    ingest(name, show_progress=False)
    return name
