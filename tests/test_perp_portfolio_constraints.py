from quant_rd_tool.perp_portfolio import allocate_notional


def test_allocate_respects_max_per_symbol():
    alloc = allocate_notional(symbols=["BTC", "ETH"], total_notional=1000, max_per_symbol=400)
    assert alloc["BTC"] <= 400
    assert alloc["ETH"] <= 400


def test_allocate_respects_total_budget():
    alloc = allocate_notional(symbols=["BTC", "ETH"], total_notional=500, max_per_symbol=400)
    assert sum(alloc.values()) <= 500


def test_allocate_respects_max_concurrent_positions():
    alloc = allocate_notional(
        symbols=["BTC", "ETH", "SOL"],
        total_notional=900,
        max_per_symbol=400,
        max_concurrent_positions=2,
    )
    active = [k for k, v in alloc.items() if v > 0]
    assert len(active) <= 2

