from quant_rd_tool.perp_exec import apply_protection_policy_to_state, evaluate_soft_sl_tp
from quant_rd_tool.perp_state import PerpSymbolState


def test_soft_sl_long():
    assert evaluate_soft_sl_tp(position_side="long", last_price=98.0, sl_price=99.0, tp_price=102.0) == "sl"


def test_soft_tp_long():
    assert evaluate_soft_sl_tp(position_side="long", last_price=103.0, sl_price=99.0, tp_price=102.0) == "tp"


def test_soft_sl_short():
    assert evaluate_soft_sl_tp(position_side="short", last_price=102.0, sl_price=101.0, tp_price=98.0) == "sl"


def test_soft_no_trigger():
    assert (
        evaluate_soft_sl_tp(position_side="long", last_price=100.0, sl_price=99.0, tp_price=102.0) is None
    )


def test_apply_policy_enables_soft_levels():
    st = PerpSymbolState()
    apply_protection_policy_to_state(
        st,
        {"fail_streak": 1, "soft_active": True},
        sl_price=99.0,
        tp_price=102.0,
        position_side="long",
    )
    assert st.soft_protection_active is True
    assert st.soft_sl_price == 99.0
    assert st.soft_tp_price == 102.0
    assert st.soft_position_side == "long"


def test_apply_policy_clears_soft_on_native_ok():
    st = PerpSymbolState(soft_protection_active=True, soft_sl_price=1.0, soft_tp_price=2.0)
    apply_protection_policy_to_state(st, {"fail_streak": 0, "soft_active": False})
    assert st.soft_protection_active is False
    assert st.soft_sl_price is None
