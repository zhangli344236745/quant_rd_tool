from __future__ import annotations

from quant_rd_tool.crypto_hft_risk import (
    RiskLimits,
    apply_fill,
    begin_risk_session,
    default_pnl_block,
    evaluate_risk,
    filter_quotes_by_risk,
    process_fills,
    refresh_risk_state,
    resolve_max_inventory_usdt,
)
from quant_rd_tool.crypto_hft_strategies import Quote


def test_apply_fill_buy_updates_avg():
    state = {"inventory_base": 0.0, "avg_entry_price": 0.0, "pnl": default_pnl_block()}
    apply_fill(state, side="buy", price=100.0, amount=1.0, fee_usdt=0.1)
    assert state["inventory_base"] == 1.0
    assert state["avg_entry_price"] == 100.0
    assert state["pnl"]["realized_usdt"] == -0.1


def test_apply_fill_sell_realizes_pnl():
    state = {
        "inventory_base": 1.0,
        "avg_entry_price": 100.0,
        "realized_pnl_usdt": 0.0,
        "pnl": default_pnl_block(),
    }
    apply_fill(state, side="sell", price=110.0, amount=1.0, fee_usdt=0.1)
    assert state["inventory_base"] == 0.0
    assert state["pnl"]["realized_usdt"] == 9.9


def test_evaluate_risk_session_loss_halts():
    state = {
        "realized_pnl_usdt": -60.0,
        "pnl": {**default_pnl_block(), "unrealized_usdt": 0.0},
        "session_start_pnl_usdt": 0.0,
        "daily_date": "2099-01-01",
        "daily_start_pnl_usdt": 0.0,
        "risk": {"halted": False, "halt_reason": None, "allow_buy": True, "allow_sell": True},
    }
    decision = evaluate_risk(
        state,
        RiskLimits(max_session_loss_usdt=50.0, max_inventory_usdt=500.0),
        inventory_usdt=0.0,
    )
    assert decision.halted
    assert "session_loss" in decision.reason


def test_evaluate_risk_inventory_blocks_side():
    state = {
        "pnl": default_pnl_block(),
        "session_start_pnl_usdt": 0.0,
        "daily_date": "2099-01-01",
        "daily_start_pnl_usdt": 0.0,
        "risk": {"halted": False, "halt_reason": None, "allow_buy": True, "allow_sell": True},
    }
    decision = evaluate_risk(
        state,
        RiskLimits(max_inventory_usdt=100.0),
        inventory_usdt=120.0,
    )
    assert not decision.halted
    assert decision.allow_buy is False
    assert decision.allow_sell is True


def test_filter_quotes_by_risk():
    quotes = [
        Quote(side="buy", price=99.0, amount=0.1),
        Quote(side="sell", price=101.0, amount=0.1),
    ]
    from quant_rd_tool.crypto_hft_risk import RiskDecision

    filtered = filter_quotes_by_risk(
        quotes,
        RiskDecision(halted=False, reason="", allow_buy=False, allow_sell=True),
    )
    assert len(filtered) == 1
    assert filtered[0].side == "sell"


def test_process_fills_dedup_by_timestamp():
    state = {"last_fill_ts_ms": 1000, "pnl": default_pnl_block(), "inventory_base": 0.0}
    fills = [
        {"timestamp": 900, "side": "buy", "price": 100, "amount": 1},
        {"timestamp": 1100, "side": "buy", "price": 101, "amount": 0.5},
    ]
    new_rows = process_fills(state, fills)
    assert len(new_rows) == 1
    assert state["last_fill_ts_ms"] == 1100


def test_begin_risk_session_resets_halt():
    state = {
        "pnl": {**default_pnl_block(), "total_usdt": 12.0},
        "risk": {"halted": True, "halt_reason": "x", "allow_buy": False, "allow_sell": False},
    }
    begin_risk_session(state)
    assert state["session_start_pnl_usdt"] == 12.0
    assert state["risk"]["halted"] is False


def test_resolve_max_inventory_prefers_bot_level():
    assert resolve_max_inventory_usdt(bot_max_inventory_usdt=300.0, strategy_params={"max_inventory_usdt": 500}) == 300.0
    assert resolve_max_inventory_usdt(bot_max_inventory_usdt=0.0, strategy_params={"max_inventory_usdt": 500}) == 500.0


def test_refresh_risk_state_updates_pnl():
    state = {"pnl": default_pnl_block(), "inventory_base": 1.0, "avg_entry_price": 100.0}
    decision, new_fills = refresh_risk_state(
        state,
        inventory={"inventory_base": 1.0, "inventory_usdt": 105.0, "mark_price": 105.0},
        mid=105.0,
        limits=RiskLimits(),
        fills=[],
        maker_fee_bps=2.0,
    )
    assert state["pnl"]["unrealized_usdt"] == 5.0
    assert not decision.halted
    assert new_fills == []
