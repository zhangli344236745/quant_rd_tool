from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_rd_tool.crypto_carry_arbitrage import (
    CarryConfig,
    accrue_open_positions,
    close_paper_carry,
    compute_basis_bps,
    compute_composite_apr,
    compute_funding_apr,
    entry_alert,
    exit_alert,
    load_config,
    open_paper_carry,
    save_config,
    scan_watchlist,
)


def test_compute_basis_bps():
    assert compute_basis_bps(spot_mark=100.0, perp_mark=100.5) == pytest.approx(50.0)


def test_compute_funding_apr():
    assert compute_funding_apr(0.0001) == pytest.approx(0.1095)


def test_compute_composite_apr():
    assert compute_composite_apr(funding_apr=0.1, basis_bps=20.0) == pytest.approx(0.1 + 20.0 / 10_000 * 365)


def test_entry_exit_alerts():
    cfg = CarryConfig(entry_threshold_apr=0.15, exit_threshold_apr=0.05)
    assert entry_alert(composite_apr=0.20, config=cfg, has_open_position=False) is True
    assert entry_alert(composite_apr=0.20, config=cfg, has_open_position=True) is False
    assert exit_alert(composite_apr=0.04, funding_rate=0.0001, config=cfg) is True
    assert exit_alert(composite_apr=0.10, funding_rate=-0.0001, config=cfg) is True


def test_config_roundtrip(tmp_path, monkeypatch):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cfg = CarryConfig(watchlist=["BTC", "ETH"], entry_threshold_apr=0.12)
    save_config(cfg)
    loaded = load_config()
    assert loaded.watchlist == ["BTC", "ETH"]
    assert loaded.entry_threshold_apr == 0.12


def test_scan_watchlist_builds_opportunities(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cca.clear_snapshot_cache()

    def _batch(symbols, **kw):
        return {s.upper(): {"spot_mark": 100.0, "perp_mark": 100.2, "funding_rate": 0.0002} for s in symbols}

    monkeypatch.setattr(cca, "fetch_watchlist_snapshots", _batch)
    cfg = CarryConfig(watchlist=["BTC"])
    rows = scan_watchlist(cfg, record_snapshot=False)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTC"
    assert rows[0]["basis_bps"] == pytest.approx(20.0)
    assert "composite_apr" in rows[0]


def test_fetch_watchlist_snapshots_uses_cache(monkeypatch):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    cca.clear_snapshot_cache()
    calls = {"n": 0}

    def _batch(symbols, **kw):
        calls["n"] += 1
        return {s.upper(): {"spot_mark": 1.0, "perp_mark": 1.0, "funding_rate": 0.0001} for s in symbols}

    monkeypatch.setattr(cca, "fetch_watchlist_snapshots", _batch)
    snap = {"spot_mark": 100.0, "perp_mark": 100.0, "funding_rate": 0.0002}
    cca._cache_snapshot("BTC", snap, quote="USDT", testnet=False)
    out = cca.fetch_market_snapshot("BTC", quote="USDT", testnet=False)
    assert out == snap
    assert calls["n"] == 0


def test_open_and_close_paper_carry(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cfg = CarryConfig(watchlist=["BTC"])
    pos = open_paper_carry(
        "BTC",
        notional_usdt=1000.0,
        config=cfg,
        spot_mark=100.0,
        perp_mark=100.1,
        funding_rate=0.0001,
    )
    assert pos["status"] == "open"
    with pytest.raises(ValueError, match="already"):
        open_paper_carry(
            "BTC",
            1000.0,
            config=cfg,
            spot_mark=100.0,
            perp_mark=100.1,
            funding_rate=0.0001,
        )
    closed = close_paper_carry(
        pos["id"],
        config=cfg,
        spot_mark=100.0,
        perp_mark=100.0,
        funding_rate=0.0001,
    )
    assert closed["status"] == "closed"
    assert closed["realized_pnl"] is not None


def test_accrue_funding_on_boundary(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cfg = CarryConfig(watchlist=["BTC"])
    entry_time = datetime(2026, 6, 12, 8, 5, tzinfo=UTC)
    pos = open_paper_carry(
        "BTC",
        notional_usdt=1000.0,
        config=cfg,
        spot_mark=100.0,
        perp_mark=100.0,
        funding_rate=0.001,
        now=entry_time,
    )
    assert pos["accrued_funding"] == 0.0
    updated = accrue_open_positions(
        cfg,
        now=datetime(2026, 6, 12, 16, 1, tzinfo=UTC),
        funding_rates={"BTC": 0.001},
    )
    assert len(updated) == 1
    assert updated[0]["accrued_funding"] == pytest.approx(1.0)


def test_preview_paper_carry(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cfg = CarryConfig(watchlist=["BTC"], default_notional_usdt=10_000)
    preview = cca.preview_paper_carry(
        "BTC",
        10_000,
        config=cfg,
        snapshot={"spot_mark": 100.0, "perp_mark": 100.2, "funding_rate": 0.0001},
    )
    assert preview["profit_estimate"]["funding_per_8h_usdt"] == pytest.approx(1.0)
    assert preview["profit_estimate"]["funding_daily_usdt"] == pytest.approx(3.0)
    assert preview["profit_estimate"]["funding_annual_usdt"] == pytest.approx(1095.0)
    assert preview["profit_estimate"]["breakeven_days"] is not None
    assert any(w["level"] == "info" for w in preview["risk_warnings"])
    plan = preview["execution_plan"]
    assert plan["base_amount"] > 0
    assert len(plan["steps"]) == 2
    assert plan["steps"][0]["side"] == "buy"
    assert plan["steps"][1]["side"] == "short"
    assert plan["expected_income"]["funding_daily_usdt"] == pytest.approx(3.0)


def test_build_carry_open_plan():
    from quant_rd_tool import crypto_carry_arbitrage as cca

    cfg = CarryConfig()
    plan = cca.build_carry_open_plan(
        "BTC",
        notional_usdt=10_000,
        spot_mark=50_000,
        perp_mark=50_100,
        funding_rate=0.0001,
        config=cfg,
    )
    assert plan["steps"][0]["market"] == "spot"
    assert plan["steps"][1]["market"] == "perp"
    assert plan["base_amount"] == pytest.approx(10_000 / (50_000 * 1.0005), rel=1e-4)
    assert plan["open_fees_usdt"] == pytest.approx(20.0)


def test_build_opportunity_includes_carry_plan():
    from quant_rd_tool import crypto_carry_arbitrage as cca

    cfg = CarryConfig(default_notional_usdt=5000)
    opp = cca.build_opportunity(
        "ETH",
        snapshot={"spot_mark": 3000, "perp_mark": 3010, "funding_rate": 0.0002},
        config=cfg,
        has_open_position=False,
    )
    assert "carry_plan" in opp
    assert "profit_estimate" in opp
    assert opp["profit_estimate"]["funding_daily_usdt"] > 0
    assert opp["carry_plan"]["notional_usdt"] == 5000
    assert len(opp["carry_plan"]["steps"]) == 2


def test_build_position_live_status(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cfg = CarryConfig(watchlist=["BTC"])
    pos = cca.open_paper_carry(
        "BTC",
        notional_usdt=1000.0,
        config=cfg,
        spot_mark=100.0,
        perp_mark=100.1,
        funding_rate=0.0001,
    )
    live = cca.build_position_live_status(
        pos,
        {"spot_mark": 101.0, "perp_mark": 100.5, "funding_rate": 0.0001},
        cfg,
    )
    assert live["open_plan"]["steps"][0]["side"] == "buy"
    assert "pnl_breakdown" in live
    assert "unrealized_pnl_if_close_now_usdt" in live["pnl_breakdown"]
    assert live["expected_income_if_hold"]["funding_7d_usdt"] > 0
    assert live["expected_income_if_hold"]["net_30d_after_open_cost_usdt"] is not None


def test_preview_negative_funding_warns(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cfg = CarryConfig(watchlist=["BTC"])
    preview = cca.preview_paper_carry(
        "BTC",
        1000,
        config=cfg,
        snapshot={"spot_mark": 100.0, "perp_mark": 100.0, "funding_rate": -0.0002},
    )
    assert preview["profit_estimate"]["funding_daily_usdt"] < 0
    assert any(w["title"] == "Funding 为负" for w in preview["risk_warnings"])


def test_preview_close_paper_carry(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cfg = CarryConfig(watchlist=["BTC"])
    entry_time = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    pos = cca.open_paper_carry(
        "BTC",
        notional_usdt=1000.0,
        config=cfg,
        spot_mark=100.0,
        perp_mark=100.1,
        funding_rate=0.0001,
        now=entry_time,
    )
    preview = cca.preview_close_paper_carry(
        pos["id"],
        config=cfg,
        snapshot={"spot_mark": 100.0, "perp_mark": 100.0, "funding_rate": 0.0001},
        now=datetime(2026, 6, 12, 16, 0, tzinfo=UTC),
    )
    assert preview["symbol"] == "BTC"
    assert preview["hold_days"] > 0
    assert "realized_pnl" in preview["pnl_estimate"]
    assert preview["position_snapshot"]["pending_periods"] >= 0
    assert preview["execution_plan"]["steps"][0]["side"] == "sell"
    assert preview["execution_plan"]["steps"][1]["side"] == "cover_short"
    assert "pnl_breakdown" in preview


def test_open_with_preview_marks_skips_fetch(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca

    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("should not fetch on open when marks provided")

    monkeypatch.setattr(cca, "fetch_market_snapshot", _boom)
    cfg = CarryConfig(watchlist=["ETH"])
    pos = open_paper_carry(
        "ETH",
        500.0,
        config=cfg,
        spot_mark=2000.0,
        perp_mark=2001.0,
        funding_rate=0.0002,
    )
    assert pos["symbol"] == "ETH"
    assert pos["status"] == "open"
