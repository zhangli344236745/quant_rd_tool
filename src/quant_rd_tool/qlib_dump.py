"""Dump akshare OHLCV frames into qlib on-disk binary format."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from qlib.utils import code_to_fname


class QlibDataDumper:
    """Minimal qlib bin dumper (compatible with qlib FileFeatureStorage)."""

    CALENDARS_DIR = "calendars"
    FEATURES_DIR = "features"
    INSTRUMENTS_DIR = "instruments"
    FREQ = "day"

    def __init__(self, qlib_dir: str | Path, *, freq: str | None = None) -> None:
        self.qlib_dir = Path(qlib_dir).expanduser()
        if freq is not None:
            self.FREQ = freq
        self._calendars_dir = self.qlib_dir / self.CALENDARS_DIR
        self._features_dir = self.qlib_dir / self.FEATURES_DIR
        self._instruments_dir = self.qlib_dir / self.INSTRUMENTS_DIR

    def _format_calendar_ts(self, ts: pd.Timestamp) -> str:
        if self.FREQ == "day":
            return pd.Timestamp(ts).strftime("%Y-%m-%d")
        return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    def _format_instrument_ts(self, ts: pd.Timestamp) -> str:
        ts = pd.Timestamp(ts)
        if self.FREQ == "day":
            return ts.strftime("%Y-%m-%d")
        return ts.strftime("%Y-%m-%d %H:%M:%S")

    def dump(self, frames: dict[str, pd.DataFrame]) -> list[str]:
        """Write all instruments; return sorted trading calendar."""
        if not frames:
            raise ValueError("frames must not be empty")

        calendars: set[pd.Timestamp] = set()
        instruments: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []

        for qlib_code, df in frames.items():
            if df.empty:
                continue
            dates = pd.to_datetime(df["date"]).sort_values()
            calendars.update(dates.tolist())
            instruments.append((qlib_code, dates.min(), dates.max()))

        calendar_list = sorted(calendars)
        self._save_calendars(calendar_list)
        self._save_instruments(instruments)

        for qlib_code, df in frames.items():
            self._dump_instrument(qlib_code, df, calendar_list)

        return [d.strftime("%Y-%m-%d") for d in calendar_list]

    def _save_calendars(self, calendar_list: list[pd.Timestamp]) -> None:
        self._calendars_dir.mkdir(parents=True, exist_ok=True)
        path = self._calendars_dir / f"{self.FREQ}.txt"
        lines = [self._format_calendar_ts(d) for d in calendar_list]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _save_instruments(self, instruments: list[tuple[str, pd.Timestamp, pd.Timestamp]]) -> None:
        self._instruments_dir.mkdir(parents=True, exist_ok=True)
        path = self._instruments_dir / "all.txt"
        rows = []
        for code, start, end in sorted(instruments, key=lambda x: x[0]):
            rows.append(
                f"{code}\t{self._format_instrument_ts(start)}\t{self._format_instrument_ts(end)}\n"
            )
        path.write_text("".join(rows), encoding="utf-8")

    def _dump_instrument(
        self,
        qlib_code: str,
        df: pd.DataFrame,
        calendar_list: list[pd.Timestamp],
    ) -> None:
        work = df.copy()
        work["date"] = pd.to_datetime(work["date"])
        work = work.set_index("date").sort_index()
        cal_df = pd.DataFrame(index=pd.DatetimeIndex(calendar_list))
        aligned = work.reindex(cal_df.index)
        if aligned.dropna(how="all").empty:
            return

        start_idx = calendar_list.index(aligned.first_valid_index())
        inst_dir = self._features_dir / code_to_fname(qlib_code).lower()
        inst_dir.mkdir(parents=True, exist_ok=True)

        field_names = ("open", "high", "low", "close", "volume", "amount")
        fields = [c for c in field_names if c in aligned.columns]
        for field in fields:
            series = aligned[field].astype(np.float32)
            bin_path = inst_dir / f"{field.lower()}.{self.FREQ}.bin"
            data = series.to_numpy(dtype="<f4")
            with bin_path.open("wb") as fp:
                np.hstack([start_idx, data]).astype("<f").tofile(fp)
