from quant_rd_tool.perp_risk import (
    CircuitBreakerState,
    apply_circuit_breaker_to_plan,
    should_block_entries,
)


def test_should_block_when_daily_loss_exceeds_threshold():
    st = CircuitBreakerState(daily_date="2026-05-28", daily_start_usdt_total=1000.0)
    blocked, _, reason = should_block_entries(
        state=st,
        usdt_total=960.0,
        max_daily_loss_pct=0.03,
        today="2026-05-28",
    )
    assert blocked is True
    assert "daily_loss_pct" in reason


def test_should_not_block_when_within_threshold():
    st = CircuitBreakerState(daily_date="2026-05-28", daily_start_usdt_total=1000.0)
    blocked, _, _ = should_block_entries(
        state=st,
        usdt_total=980.0,
        max_daily_loss_pct=0.03,
        today="2026-05-28",
    )
    assert blocked is False


def test_circuit_breaker_resets_on_new_day():
    st = CircuitBreakerState(daily_date="2026-05-27", daily_start_usdt_total=1000.0)
    blocked, updated, _ = should_block_entries(
        state=st,
        usdt_total=500.0,
        max_daily_loss_pct=0.03,
        today="2026-05-28",
    )
    assert blocked is False
    assert updated.daily_date == "2026-05-28"
    assert updated.daily_start_usdt_total == 500.0


def test_apply_circuit_breaker_strips_open_keeps_close():
    plan = {"close": True, "open": True}
    out = apply_circuit_breaker_to_plan(plan=plan, blocked=True)
    assert out["close"] is True
    assert out["open"] is False
