from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from quant_rd_tool.crypto_options_backtest import (
    align_iv_to_bars,
    bs_call_price,
    run_options_overlay,
)
from quant_rd_tool.crypto_zipline_pandas import run_bar_backtest
from quant_rd_tool.crypto_zipline_strategies import get_strategy, list_strategies


def _sample_df(n: int = 60) -> pd.DataFrame:
    rows = []
    price = 100_000.0
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(n):
        price += 200 if i % 10 < 6 else -150
        rows.append(
            {
                "date": (base + timedelta(hours=15 * i)).isoformat(),
                "open": price,
                "high": price + 100,
                "low": price - 100,
                "close": price,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


def test_bs_call_price_positive():
    p = bs_call_price(100_000, 100_000, iv=0.5, dte_days=14)
    assert p > 0


def test_align_iv_to_bars_forward_fill():
    df = _sample_df(10)
    hist = [
        {"ts": df.iloc[0]["date"], "atm_iv": 0.5, "strike": 100_000},
        {"ts": df.iloc[5]["date"], "atm_iv": 0.6, "strike": 100_000},
    ]
    aligned = align_iv_to_bars(df, hist)
    assert len(aligned) == len(df)
    assert float(aligned.iloc[3]["atm_iv"]) == 0.5
    assert float(aligned.iloc[7]["atm_iv"]) == 0.6


def test_run_options_overlay_call(tmp_path: Path):
    df = _sample_df(50)
    work = df.copy()
    work["target"] = 0.0
    work.loc[work.index >= 20, "target"] = 1.0
    spot = run_bar_backtest(work, capital_base=100_000, warmup=5)
    hist = [
        {"ts": df.iloc[0]["date"], "atm_iv": 0.45, "strike": 100_000},
    ]
    hist_path = tmp_path / "crypto" / "options_iv"
    hist_path.mkdir(parents=True)
    import json

    with (hist_path / "BTC.jsonl").open("w") as f:
        f.write(json.dumps(hist[0]) + "\n")

    out = run_options_overlay(
        df,
        spot,
        symbol="BTC",
        data_dir=str(tmp_path / "crypto"),
        overlay_id="call_overlay",
        params={"options_pct": 0.2, "dte_days": 14},
        capital_base=100_000,
    )
    assert out["enabled"]
    assert out["combined_equity_curve"]
    assert out["combined_metrics"]["trade_count"] >= 0


def test_options_strategies_registered():
    ids = {s["id"] for s in list_strategies()}
    assert "opt_call_overlay" in ids
    assert "opt_auto_pack" in ids
    spec = get_strategy("opt_call_overlay")
    assert spec and spec.get("category") == "options"


def test_resolve_overlay_from_strategy_pack():
    from quant_rd_tool.crypto_options_strategies import resolve_overlay_from_strategy_pack

    pack = {
        "headline": "卖出宽跨",
        "strategies": [
            {"id": "sell_strangle", "name": "卖出宽跨", "score": 0.8, "rationale": "IV 高"},
            {"id": "buy_call", "name": "买 Call", "score": 0.5},
        ],
    }
    r = resolve_overlay_from_strategy_pack(pack)
    assert r["overlay_id"] == "short_straddle_iv"
    assert r["strategy_kind"] == "sell_strangle"

    wait = resolve_overlay_from_strategy_pack(
        {"strategies": [{"id": "wait", "name": "观望", "score": 0.4}]}
    )
    assert wait["overlay_id"] is None
