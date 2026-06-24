"""Export A-share OHLCV / backtest artifacts."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_rd_tool.stock_codes import to_ak_code, to_qlib_code
from quant_rd_tool.crypto_zipline_storage import load_run
from quant_rd_tool.crypto_zipline_zipline_engine import _bar_timestamps, _slice_bars_for_backtest
from quant_rd_tool.stock_zipline_bundle import load_ohlcv_window
from quant_rd_tool.stock_zipline_timeframes import normalize_timeframe


def export_ohlcv_dataframe(
    symbol: str,
    *,
    data_dir: str | Path,
    timeframe: str,
    start: str | None = None,
    end: str | None = None,
    lookback_days: int = 800,
) -> pd.DataFrame:
    tf = normalize_timeframe(timeframe)
    code = to_ak_code(symbol)
    df = load_ohlcv_window(
        code,
        data_dir=data_dir,
        timeframe=tf,
        lookback_days=lookback_days,
        range_start=start,
        range_end=end,
    )
    if start and end:
        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
        df = _slice_bars_for_backtest(df, start=start_ts, end=end_ts, warmup_bars=0)
    return df


def build_export_zip(
    symbol: str,
    *,
    data_dir: str | Path,
    timeframe: str,
    start: str | None = None,
    end: str | None = None,
    lookback_days: int = 800,
    run_id: str | None = None,
) -> bytes:
    tf = normalize_timeframe(timeframe)
    sym = to_qlib_code(symbol)
    df = export_ohlcv_dataframe(
        symbol,
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
            "market": "stock",
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
    sym = to_qlib_code(symbol)
    tf = normalize_timeframe(timeframe)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{sym}_{tf}_{ts}.{ext}"
