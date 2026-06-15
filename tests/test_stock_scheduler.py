"""Tests for A-share scheduled analysis cycle."""

from __future__ import annotations

from unittest.mock import patch

from quant_rd_tool.stock_scheduler import resolve_stock_symbols, run_stock_scheduled_cycle


def test_resolve_watchlist_symbols(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool.watchlist import Watchlist

    Watchlist().add("600519", name="茅台")
    codes = resolve_stock_symbols([], use_watchlist=True)
    assert codes == ["600519"]


def test_run_stock_cycle_mocked(tmp_path):
    fake = {
        "code": "600519",
        "qlib_code": "SH600519",
        "summary": {"stance": "偏多"},
        "report": {"symbol": "SH600519", "narrative": {"stance": "偏多"}},
    }
    with patch(
        "quant_rd_tool.akshare_stocks.run_qlib_stock_analysis",
        return_value=fake,
    ) as mock_run:
        results = run_stock_scheduled_cycle(
            ["600519"],
            data_dir=tmp_path / "data" / "stocks",
            save_snapshot=False,
        )
    mock_run.assert_called_once()
    assert results[0]["code"] == "600519"
    assert results[0]["narrative"]["stance"] == "偏多"


def test_run_stock_cycle_empty_watchlist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    results = run_stock_scheduled_cycle([], use_watchlist=True, save_snapshot=False)
    assert results[0]["error"]
