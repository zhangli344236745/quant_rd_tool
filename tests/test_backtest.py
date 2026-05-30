"""Backtest engine tests (no live akshare)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_rd_tool.backtest_engine import _extract_metrics, _momentum_panel, _topk_backtest
from quant_rd_tool.qlib_dump import QlibDataDumper


def _fake_frames(codes: list[str], n: int = 80) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2024-01-02", periods=n)
    frames = {}
    for i, code in enumerate(codes):
        ret = rng.normal(0.001 * (i + 1), 0.02, size=n)
        close = 100 * (1 + ret).cumprod()
        frames[code] = pd.DataFrame(
            {
                "date": dates,
                "symbol": code,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": rng.integers(1_000_000, 5_000_000, n),
            }
        )
    return frames


def test_qlib_dump_roundtrip(tmp_path):
    frames = _fake_frames(["SH600519", "SH601318"])
    dumper = QlibDataDumper(tmp_path)
    cal = dumper.dump(frames)
    assert len(cal) >= 80
    assert (tmp_path / "calendars" / "day.txt").exists()
    assert (tmp_path / "instruments" / "all.txt").exists()


def test_topk_backtest_produces_metrics():
    codes = ["SH600519", "SH601318", "SZ000858"]
    frames = _fake_frames(codes)
    close = pd.concat(
        [f.set_index(pd.to_datetime(f["date"]))["close"].rename(c) for c, f in frames.items()],
        axis=1,
    )
    scores = _momentum_panel(frames, lookback=10)
    report, _weights = _topk_backtest(scores.iloc[15:], close.iloc[15:], topk=2, initial_cash=1e6)
    metrics = _extract_metrics(report)
    assert metrics["trading_days"] > 10
    assert "total_return" in metrics
