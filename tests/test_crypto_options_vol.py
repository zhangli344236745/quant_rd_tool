from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from quant_rd_tool.crypto_options_advisor import advise_item, build_scan_advice
from quant_rd_tool.crypto_options_data import (
    append_snapshot,
    parse_option_symbol,
    pick_atm_contract,
)
from quant_rd_tool.crypto_options_vol_scan import (
    iv_change_24h,
    iv_percentile,
    run_volatility_scan,
)


def test_parse_option_symbol():
    meta = parse_option_symbol("BTC-250328-85000-C")
    assert meta
    assert meta["base"] == "BTC"
    assert meta["strike"] == 85000.0
    assert meta["side"] == "C"


def test_pick_atm_contract():
    now = datetime.now(UTC)
    exp = (now + timedelta(days=28)).strftime("%y%m%d")
    marks = [
        {
            "symbol": f"BTC-{exp}-80000-C",
            "markIV": "0.55",
        },
        {
            "symbol": f"BTC-{exp}-85000-C",
            "markIV": "0.60",
        },
        {
            "symbol": f"BTC-{exp}-90000-C",
            "markIV": "0.58",
        },
    ]
    atm = pick_atm_contract(marks, "BTC", 85200.0)
    assert atm
    assert atm["strike"] == 85000.0
    assert atm["atm_iv"] == 0.6


def test_iv_percentile_and_change():
    hist = [0.4, 0.45, 0.5, 0.55, 0.6]
    assert iv_percentile(0.6, hist) == 100.0
    rows = [
        {"ts": (datetime.now(UTC) - timedelta(hours=25)).isoformat(), "atm_iv": 0.5},
        {"ts": datetime.now(UTC).isoformat(), "atm_iv": 0.6},
    ]
    chg = iv_change_24h(0.6, rows[:-1])
    assert chg is not None
    assert chg == pytest.approx(20.0, rel=0.1)


def test_run_volatility_scan_mocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base_ts = datetime.now(UTC)
    exp = (base_ts + timedelta(days=30)).strftime("%y%m%d")

    def fake_mark(*_a, **_k):
        return [
            {"symbol": f"BTC-{exp}-100000-C", "markIV": "0.70"},
            {"symbol": f"ETH-{exp}-3500-C", "markIV": "0.65"},
        ]

    def fake_index(bases=None, **_k):
        return {"BTC": 100000.0, "ETH": 3500.0}

    client = MagicMock()
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_data.fetch_mark_rows",
        lambda **kw: fake_mark(),
    )
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_data.fetch_index_prices",
        fake_index,
    )

    for i in range(10):
        append_snapshot(
            {
                "base": "BTC",
                "ts": (base_ts - timedelta(days=10 - i)).isoformat(),
                "atm_iv": 0.45 + i * 0.02,
            },
            data_dir="data/crypto",
        )

    scan = run_volatility_scan(
        symbols=["BTC", "ETH"],
        data_dir="data/crypto",
        persist_snapshot=False,
        client=client,
    )
    assert len(scan["items"]) == 2
    btc = next(x for x in scan["items"] if x["base"] == "BTC")
    assert btc.get("atm_iv") == 0.7
    assert btc.get("rank") == 1
    advice = build_scan_advice(scan)
    assert advice["advice"]
    assert advise_item(btc)["stance"]


def test_render_markdown_options_actions_do_not_shadow_analysis():
    from quant_rd_tool.crypto_analysis import _render_markdown

    report = {
        "pair": "BTC/USDT",
        "timeframe": "1d",
        "generated_at": "2026-01-01",
        "period": {"start": "2024-01-01", "end": "2026-01-01", "bars": 100},
        "analysis": {
            "price": {"latest_close": 100.0, "period_high": 110.0, "period_low": 90.0},
            "returns": {"5d": 0.01, "20d": 0.02},
            "technical": {
                "ma_alignment": "多头排列",
                "rsi_14": 55,
                "rsi_zone": "中性",
            },
        },
        "combined_signal": {
            "stance": "看涨",
            "action": "buy",
            "confidence": 0.6,
            "technical": {"stance": "看涨"},
            "ml": {"stance": None},
            "agreement": "一致",
            "reasons": [],
        },
        "narrative": {
            "summary": "test",
            "advice": "hold",
            "risks": ["r1"],
            "disclaimer": "d",
            "investment_brief": {},
        },
        "options_vol": {
            "enabled": True,
            "scan_item": {"atm_iv": 0.5, "iv_percentile": 85, "iv_change_24h_pct": 12},
            "cross_view": {"summary": "cross"},
            "advice": {"actions": ["期权建议一", "期权建议二"]},
        },
    }
    md = _render_markdown(report)
    assert "最新价：100.0" in md
    assert "期权建议一" in md


def test_vol_scan_cache_reuses_payload(monkeypatch):
    from quant_rd_tool.crypto_options_vol_scan import (
        clear_vol_scan_cache,
        get_or_run_volatility_scan,
    )

    calls = {"n": 0}

    def fake_run(**_kwargs):
        calls["n"] += 1
        return {"scanned_at": "t", "items": [], "config": {}}

    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_vol_scan.run_volatility_scan",
        fake_run,
    )
    clear_vol_scan_cache("data/crypto")
    get_or_run_volatility_scan(symbols=["BTC"], data_dir="data/crypto", cache_seconds=60)
    get_or_run_volatility_scan(symbols=["BTC"], data_dir="data/crypto", cache_seconds=60)
    assert calls["n"] == 1


def test_fetch_options_context_includes_peer_rank(monkeypatch):
    from quant_rd_tool.crypto_options_integration import fetch_options_context

    def fake_scan(**_kwargs):
        return {
            "scanned_at": "2026-01-01T00:00:00+00:00",
            "items": [
                {"base": "BTC", "atm_iv": 0.7, "rank": 1, "alert_level": "hot"},
                {"base": "ETH", "atm_iv": 0.5, "rank": 2, "alert_level": "normal"},
            ],
        }

    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_integration.get_or_run_volatility_scan",
        fake_scan,
    )
    monkeypatch.setattr(
        "quant_rd_tool.crypto_options_integration.advise_item",
        lambda row: {"stance": "观望", "summary": "t", "actions": [], "risks": []},
    )
    ctx = fetch_options_context("ETH", persist_snapshot=False)
    assert ctx["enabled"] is True
    assert ctx["peer_rank"] == 2
    assert ctx["peer_count"] == 2
    assert ctx["hottest_peer"] == "BTC"


def test_synthesize_cross_market_bullish_high_iv():
    from quant_rd_tool.crypto_options_integration import synthesize_cross_market_view

    ctx = {
        "enabled": True,
        "alert_level": "hot",
        "iv_percentile": 90,
        "iv_change_24h_pct": 15,
        "atm_iv": 0.7,
        "advice": {"stance": "波动溢价偏高"},
    }
    cross = synthesize_cross_market_view(
        spot_stance="看涨",
        spot_action="buy",
        options_ctx=ctx,
    )
    assert cross["alignment"] in ("分歧", "谨慎共振", "共振", "补充")
    assert cross["summary"]


def test_advise_high_iv_rising():
    row = {
        "base": "BTC",
        "atm_iv": 0.8,
        "iv_percentile": 92,
        "iv_change_24h_pct": 15,
        "alert_level": "hot",
        "rank": 1,
    }
    out = advise_item(row)
    assert "波动溢价偏高" in out["stance"] or "偏高" in out["summary"]
