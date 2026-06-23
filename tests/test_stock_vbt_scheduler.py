from __future__ import annotations

import json

import pandas as pd

from quant_rd_tool.stock_vbt_lab import refresh_universe_data
from quant_rd_tool.stock_vbt_scheduler import (
    VbtSchedulerConfig,
    load_config,
    run_daily_pipeline,
    save_config,
)


def test_refresh_universe_data_mock(monkeypatch):
    from quant_rd_tool import stock_vbt_lab as lab

    calls: list[str] = []

    def _fake_load(sym, start, end, **kw):
        calls.append(sym)
        return pd.DataFrame({"date": ["2023-01-02"], "close": [10.0]})

    monkeypatch.setattr(lab, "load_ohlcv", _fake_load)
    out = refresh_universe_data(["600519", "000001"], "2023-01-01", "2023-06-01")
    assert len(calls) == 2
    assert len(out["refreshed"]) == 2


def test_run_daily_pipeline_mock(monkeypatch, tmp_path):
    from quant_rd_tool import stock_vbt_scheduler as sched

    monkeypatch.setattr(sched, "SCHEDULER_DIR", tmp_path / "scheduler")
    monkeypatch.setattr(sched, "SIGNALS_PATH", tmp_path / "signals" / "latest.json")
    monkeypatch.setattr(
        sched,
        "refresh_universe_data",
        lambda *a, **kw: {"refreshed": ["SH600519"], "errors": []},
    )
    monkeypatch.setattr(
        sched,
        "screen_universe",
        lambda **kw: {
            "run_id": "ml1",
            "items": [{"symbol": "SH600519", "score": 0.02}],
        },
    )
    monkeypatch.setattr(
        sched,
        "optimize_portfolio",
        lambda **kw: {
            "run_id": "p1",
            "weights": {"SH600519": 1.0},
            "sharpe_ratio": 1.2,
        },
    )

    cfg = VbtSchedulerConfig(
        symbols=["600519"],
        use_watchlist=False,
        refresh_data=True,
        optuna_trials=0,
    )
    result = run_daily_pipeline(cfg)
    assert result["ml_rankings"]
    assert sched.SIGNALS_PATH.is_file()
    saved = json.loads(sched.SIGNALS_PATH.read_text(encoding="utf-8"))
    assert saved["portfolio"]["run_id"] == "p1"


def test_scheduler_config_roundtrip(tmp_path, monkeypatch):
    from quant_rd_tool import stock_vbt_scheduler as sched

    monkeypatch.setattr(sched, "SCHEDULER_DIR", tmp_path)
    monkeypatch.setattr(sched, "CONFIG_PATH", tmp_path / "config.json")
    cfg = VbtSchedulerConfig(enabled=True, optuna_trials=10, refresh_data=False)
    save_config(cfg)
    loaded = load_config()
    assert loaded.enabled is True
    assert loaded.optuna_trials == 10
    assert loaded.refresh_data is False
