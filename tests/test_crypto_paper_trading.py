from __future__ import annotations

from quant_rd_tool.crypto_paper_trading import (
    PaperAccount,
    apply_action,
    check_soft_protection,
    compute_performance,
)


def _account() -> PaperAccount:
    return PaperAccount(symbol="BTC", quote="USDT", initial_cash=10_000.0, cash=10_000.0)


def test_buy_then_sell_realizes_pnl():
    acc = _account()
    apply_action(acc, action="buy", price=100.0, ts="t0")
    assert acc.position.base_amount > 0
    assert acc.cash < 1.0  # spent ~all cash
    apply_action(acc, action="sell", price=110.0, ts="t1")
    assert acc.position.base_amount == 0
    assert acc.realized_pnl > 0  # price up 10% beats fees+slippage
    assert acc.cash > 10_000.0


def test_fees_and_slippage_reduce_proceeds():
    acc = _account()
    apply_action(acc, action="buy", price=100.0, ts="t0")
    apply_action(acc, action="sell", price=100.0, ts="t1")
    # round trip at flat price must lose to fees + slippage
    assert acc.realized_pnl < 0
    assert acc.total_fees > 0


def test_hold_records_equity_only():
    acc = _account()
    out = apply_action(acc, action="hold", price=100.0, ts="t0")
    assert out["order"] is None
    assert len(acc.equity_curve) == 1
    assert acc.position.base_amount == 0


def test_soft_protection_stop_loss():
    acc = _account()
    apply_action(acc, action="buy", price=100.0, ts="t0", sl_price=95.0, tp_price=115.0)
    hit = check_soft_protection(acc, price=94.0, ts="t1")
    assert hit is not None
    assert hit["triggered"] == "stop_loss"
    assert acc.position.base_amount == 0


def test_soft_protection_take_profit():
    acc = _account()
    apply_action(acc, action="buy", price=100.0, ts="t0", sl_price=95.0, tp_price=115.0)
    hit = check_soft_protection(acc, price=116.0, ts="t1")
    assert hit is not None
    assert hit["triggered"] == "take_profit"


def test_compute_performance_metrics():
    acc = _account()
    apply_action(acc, action="buy", price=100.0, ts="t0")
    apply_action(acc, action="sell", price=120.0, ts="t1")
    apply_action(acc, action="buy", price=120.0, ts="t2")
    apply_action(acc, action="sell", price=110.0, ts="t3")
    perf = compute_performance(acc)
    assert perf["closed_trades"] == 2
    assert perf["win_rate"] == 0.5
    assert perf["trade_count"] == 4
    assert perf["max_drawdown"] >= 0
    assert "profit_factor" in perf


def test_persistence_round_trip(tmp_path):
    acc = _account()
    apply_action(acc, action="buy", price=100.0, ts="t0", sl_price=95.0)
    path = tmp_path / "paper.json"
    acc.save(path)
    loaded = PaperAccount.load(path, symbol="BTC", quote="USDT", initial_cash=10_000.0)
    assert loaded.position.base_amount == acc.position.base_amount
    assert loaded.position.sl_price == 95.0
    assert len(loaded.trades) == 1
