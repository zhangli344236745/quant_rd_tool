"""Single-stock analysis tests (offline)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from quant_rd_tool.stock_analysis import analyze_stock
from quant_rd_tool.stock_analyzer import analyze_ohlcv, build_narrative
from quant_rd_tool.stock_storage import csv_path, load_csv, qlib_path, save_csv


def _fake_df(code: str = "SH600519", n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2024-01-02", periods=n)
    ret = rng.normal(0.0005, 0.018, n)
    close = 1800 * (1 + ret).cumprod()
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": code,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1e6, 5e6, n),
        }
    )


def test_analyze_ohlcv_structure():
    analysis = analyze_ohlcv(_fake_df())
    assert analysis["symbol"] == "SH600519"
    assert analysis["period"]["bars"] == 120
    assert "returns" in analysis
    narrative = build_narrative(analysis)
    assert narrative["stance"] in ("偏多", "谨慎", "中性")


def test_analyze_stock_offline(tmp_path):
    df = _fake_df()
    root = tmp_path / "SH600519"
    save_csv(df, csv_path(root))

    report = analyze_stock(
        "600519",
        start_date="2024-01-01",
        end_date="2024-12-31",
        data_dir=tmp_path,
        refresh=False,
        with_benchmark=False,
    )
    assert report["symbol"] == "SH600519"
    assert qlib_path(root).exists()
    assert (root / "report.json").exists()
    assert (root / "report.md").exists()
    loaded = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert loaded["analysis"]["period"]["bars"] == 120
    assert load_csv(csv_path(root)).shape[0] == 120
