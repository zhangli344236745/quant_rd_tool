from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_rd_tool.crypto_ws_hft import (
    build_cycle_plan,
    handle_book_update,
    should_process_update,
    update_latency_stats,
)
from quant_rd_tool.crypto_ws_hft_storage import WsHftBotConfig, default_bot_state, save_bot_config


@pytest.fixture
def book():
    return json.loads((Path(__file__).parent / "fixtures" / "hft_book.json").read_text())


def test_should_process_every_update():
    cfg = WsHftBotConfig(bot_id="x", trigger_mode="every_update", throttle_ms=50)
    assert should_process_update(cfg, last_process_ns=0, now_ns=1_000_000)
    assert should_process_update(cfg, last_process_ns=999_999_999, now_ns=1_000_000_000)


def test_should_process_throttle():
    cfg = WsHftBotConfig(bot_id="x", trigger_mode="throttle", throttle_ms=20)
    assert should_process_update(cfg, last_process_ns=None, now_ns=100)
    assert not should_process_update(cfg, last_process_ns=100, now_ns=10_000_000)
    assert should_process_update(cfg, last_process_ns=100, now_ns=21_000_000)


def test_update_latency_stats():
    state = default_bot_state("x")
    update_latency_stats(state, 1000)
    update_latency_stats(state, 2000)
    lat = state["latency_us"]
    assert lat["last"] == 2000
    assert lat["p50"] == 1500


def test_build_cycle_plan(book):
    cfg = WsHftBotConfig(bot_id="btc", strategy_id="classic_mm")
    state = default_bot_state("btc")
    plan = build_cycle_plan(cfg, book, state, [], {"inventory_usdt": 0})
    assert plan.summary["mid"] == 100.05
    assert len(plan.desired) >= 1


@pytest.mark.asyncio
async def test_handle_book_update_dry_run(tmp_path, monkeypatch, book):
    from quant_rd_tool import crypto_ws_hft_storage as st

    monkeypatch.setattr(st, "WS_HFT_DIR", tmp_path)
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "BOTS_INDEX_PATH", tmp_path / "bots.json")
    (tmp_path / "bots").mkdir(parents=True)
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "events").mkdir(parents=True)

    cfg = WsHftBotConfig(bot_id="btc", dry_run=True, trigger_mode="every_update")
    save_bot_config(cfg)

    class _FakeEx:
        async def fetch_open_orders(self, symbol):
            return []

        async def fetch_positions(self, symbols):
            return [{"symbol": symbols[0], "contracts": 0, "side": "long"}]

        async def fetch_ticker(self, symbol):
            return {"last": 100}

        async def close(self):
            return None

    from quant_rd_tool import crypto_ws_hft as eng

    monkeypatch.setattr(eng, "is_kill_switch_active", lambda: False)

    result = await handle_book_update(
        "btc",
        book,
        live_trading=False,
        exchange=_FakeEx(),
    )
    assert result["dry_run"] is True
    assert result["placed"] == 0
    assert result["latency_us"] >= 0
