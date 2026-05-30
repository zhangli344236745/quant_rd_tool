from quant_rd_tool.perp_exec import decide_protection_policy


def test_native_ok_resets_streak_and_disables_soft():
    out = decide_protection_policy(current_fail_streak=2, native_ok=True, max_failures=3)
    assert out["fail_streak"] == 0
    assert out["soft_active"] is False
    assert out["force_close"] is False


def test_native_fail_increments_streak_and_enables_soft():
    out = decide_protection_policy(current_fail_streak=1, native_ok=False, max_failures=3)
    assert out["fail_streak"] == 2
    assert out["soft_active"] is True
    assert out["force_close"] is False


def test_force_close_when_reaches_max_failures():
    out = decide_protection_policy(current_fail_streak=2, native_ok=False, max_failures=3)
    assert out["fail_streak"] == 3
    assert out["soft_active"] is True
    assert out["force_close"] is True

