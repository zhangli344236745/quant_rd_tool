"""Export OHLCV / backtest artifacts for download."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_zipline_bundle import load_ohlcv_window
from quant_rd_tool.crypto_zipline_zipline_engine import _bar_timestamps, _slice_bars_for_backtest
from quant_rd_tool.crypto_zipline_storage import load_run
from quant_rd_tool.crypto_zipline_timeframes import normalize_timeframe


def export_ohlcv_dataframe(
    symbol: str,
    *,
    data_dir: str | Path,
    timeframe: str,
    start: str | None = None,
    end: str | None = None,
    lookback_days: int = 90,
) -> pd.DataFrame:
    tf = normalize_timeframe(timeframe)
    df = load_ohlcv_window(
        symbol,
        data_dir=data_dir,
        timeframe=tf,
        lookback_days=lookback_days,
        range_start=start,
        range_end=end,
    )
    if start and end:
        start_ts = pd.Timestamp(start, tz="UTC").tz_convert("UTC").tz_localize(None)
        end_ts = pd.Timestamp(end, tz="UTC").tz_convert("UTC").tz_localize(None)
        df = _slice_bars_for_backtest(df, start=start_ts, end=end_ts, warmup_bars=0)
    return df


def write_ohlcv_csv(
    symbol: str,
    *,
    data_dir: str | Path,
    timeframe: str,
    dest: Path,
    start: str | None = None,
    end: str | None = None,
    lookback_days: int = 90,
) -> Path:
    df = export_ohlcv_dataframe(
        symbol,
        data_dir=data_dir,
        timeframe=timeframe,
        start=start,
        end=end,
        lookback_days=lookback_days,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    return dest


def build_export_zip(
    symbol: str,
    *,
    data_dir: str | Path,
    timeframe: str,
    start: str | None = None,
    end: str | None = None,
    lookback_days: int = 90,
    run_id: str | None = None,
) -> bytes:
    tf = normalize_timeframe(timeframe)
    sym = symbol.strip().upper()
    df = export_ohlcv_dataframe(
        sym,
        data_dir=data_dir,
        timeframe=tf,
        start=start,
        end=end,
        lookback_days=lookback_days,
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        ohlcv_name = f"{sym}_{tf}_ohlcv.csv"
        zf.writestr(ohlcv_name, df.to_csv(index=False))
        meta = {
            "symbol": sym,
            "timeframe": tf,
            "bars": len(df),
            "start": start,
            "end": end,
            "exported_at": now_iso(),
        }
        if not df.empty:
            ts = _bar_timestamps(df)
            meta["first_bar"] = str(ts.min())
            meta["last_bar"] = str(ts.max())
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

        if run_id:
            run = load_run(data_dir, run_id)
            if run:
                zf.writestr(
                    f"run_{run_id}.json",
                    json.dumps(run, ensure_ascii=False, indent=2, default=str),
                )
                eq = run.get("equity_curve") or []
                if eq:
                    eq_df = pd.DataFrame(eq)
                    zf.writestr(f"run_{run_id}_equity.csv", eq_df.to_csv(index=False))
                trades = run.get("trades") or []
                if trades:
                    tr_df = pd.DataFrame(trades)
                    zf.writestr(f"run_{run_id}_trades.csv", tr_df.to_csv(index=False))

    return buf.getvalue()


def export_filename(symbol: str, timeframe: str, *, ext: str = "csv") -> str:
    sym = cxt.to_qlib_code(symbol)
    tf = normalize_timeframe(timeframe)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{sym}_{tf}_{ts}.{ext}"
