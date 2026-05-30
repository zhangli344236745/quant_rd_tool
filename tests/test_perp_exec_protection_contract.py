from quant_rd_tool.perp_exec import should_force_close_on_protection_fail


def test_force_close_after_n_failures():
    assert should_force_close_on_protection_fail(fail_streak=0, max_failures=3) is False
    assert should_force_close_on_protection_fail(fail_streak=2, max_failures=3) is False
    assert should_force_close_on_protection_fail(fail_streak=3, max_failures=3) is True

