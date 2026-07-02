from __future__ import annotations

from quant_rd_tool.crypto_polymarket_stream import consume_dirty, get_stream_status, start_stream, stop_stream


def test_stream_status_rest():
    stop_stream()
    st = get_stream_status()
    assert st["mode"] == "rest"


def test_stream_start_stop_no_tokens():
    st = start_stream([], mode="hybrid", poll_interval_s=2.0)
    assert st["mode"] == "hybrid"
    stop_stream()
    assert consume_dirty() is False
