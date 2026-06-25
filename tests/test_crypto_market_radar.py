import json
from pathlib import Path

import pytest

from quant_rd_tool.crypto_market_radar import (
    MarketRadarConfig,
    _realized_vol_pct,
    diff_binance_listings,
    diff_coingecko_new_coins,
    empty_scan_result,
    evaluate_market_radar_alerts,
    load_config,
    save_config,
    scan_markets,
)

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def radar_tmp(tmp_path, monkeypatch):
    radar = tmp_path / "market_radar"
    radar.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("quant_rd_tool.crypto_market_radar.RADAR_DIR", radar)
    return radar


def test_realized_vol_pct():
    closes = [100.0, 101.0, 100.5, 102.0, 101.0]
    vol = _realized_vol_pct(closes)
    assert vol is not None
    assert vol > 0


def test_diff_binance_listings_new_symbol(radar_tmp):
    spot = json.loads((FIX / "binance_spot_exchange_info.json").read_text())
    perp = json.loads((FIX / "binance_perp_exchange_info.json").read_text())

    snap = radar_tmp / "binance_snapshot.json"
    snap.write_text(
        json.dumps({"spot": ["BTCUSDT"], "perp": ["BTCUSDT"], "bootstrapped": True}),
        encoding="utf-8",
    )

    def http_get(url: str, params=None):
        if "fapi" in url:
            return perp
        if "exchangeInfo" in url:
            return spot
        raise AssertionError(url)

    items, _ = diff_binance_listings(http_get=http_get, snapshot_path=snap)
    assert len(items) == 1
    assert items[0]["symbol"] == "NEWCOINUSDT"
    assert items[0]["market_type"] == "spot"


def test_diff_coingecko_new_coin(radar_tmp):
    coin_list = json.loads((FIX / "coingecko_coins_list.json").read_text())
    snap = radar_tmp / "coingecko_snapshot.json"
    snap.write_text(
        json.dumps({"coin_ids": ["bitcoin", "ethereum"], "bootstrapped": True}),
        encoding="utf-8",
    )

    def http_get(url: str, params=None):
        if url.endswith("/coins/list"):
            return coin_list
        if "/coins/markets" in url:
            return [
                {
                    "id": "newcoin",
                    "symbol": "new",
                    "name": "New Coin",
                    "market_cap": 1000000,
                    "price_change_percentage_24h": 12.5,
                }
            ]
        raise AssertionError(url)

    items, _ = diff_coingecko_new_coins(http_get=http_get, snapshot_path=snap)
    assert len(items) == 1
    assert items[0]["coin_id"] == "newcoin"


def test_scan_markets_with_mocks(radar_tmp):
    spot_info = json.loads((FIX / "binance_spot_exchange_info.json").read_text())
    perp_info = json.loads((FIX / "binance_perp_exchange_info.json").read_text())
    coin_list = json.loads((FIX / "coingecko_coins_list.json").read_text())

    tickers = [
        {
            "symbol": "BTCUSDT",
            "lastPrice": "50000",
            "priceChangePercent": "10.5",
            "quoteVolume": "1000000000",
        },
        {
            "symbol": "ETHUSDT",
            "lastPrice": "3000",
            "priceChangePercent": "-9.0",
            "quoteVolume": "500000000",
        },
    ]

    def http_get(url: str, params=None):
        if "fapi" in url and "exchangeInfo" in url:
            return perp_info
        if "exchangeInfo" in url:
            return spot_info
        if url.endswith("/coins/list"):
            return coin_list
        if "/coins/markets" in url:
            return []
        if "ticker/24hr" in url:
            return tickers
        if "klines" in url:
            return [[0, 1, 1, 1, 100, 0]] * 24 + [[0, 1, 1, 1, 105, 0]]
        raise AssertionError(url)

    cfg = MarketRadarConfig(min_24h_change_pct=8.0, scan_dedupe_sec=0)
    result = scan_markets(cfg, force=True, http_get=http_get)
    assert result["scan_id"]
    assert len(result["high_volatility"]) >= 2
    assert any(r["high_vol"] for r in result["high_volatility"])


def test_empty_scan_result():
    empty = empty_scan_result()
    assert empty["binance_new"] == []


def test_config_roundtrip(radar_tmp):
    cfg = MarketRadarConfig(top_n_liquidity=150, min_24h_change_pct=12.0)
    save_config(cfg)
    loaded = load_config()
    assert loaded.top_n_liquidity == 150
    assert loaded.min_24h_change_pct == 12.0


def test_evaluate_alerts_high_vol(radar_tmp):
    cfg = MarketRadarConfig(alert_cooldown_sec=0)
    scan = {
        "binance_new": [],
        "coingecko_new": [],
        "high_volatility": [
            {
                "symbol": "BTCUSDT",
                "high_vol": True,
                "change_pct_24h": 12.0,
                "realized_vol_pct": 6.0,
            }
        ],
    }
    alerts = evaluate_market_radar_alerts(scan, cfg)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "high_volatility"
