# Crypto Market Radar — Design Spec

**Approved:** 2026-06-24  
**Scope:** Binance new listings, CoinGecko new coins, high-volatility scanner with builtin timer and Bark alerts

## User decisions

| Dimension | Choice |
|-----------|--------|
| New listings | **Both:** Binance (spot + USDT perp) + CoinGecko global (two tabs) |
| Volatility | **Both:** 24h `|priceChangePercent|` and realized vol (switchable sort) |
| Scheduling | Builtin scan + optional Bark; **no** Schedules page integration (v1) |

## Goals

1. Detect newly listed Binance spot/USDT-M perp symbols via snapshot diff.
2. Detect newly indexed CoinGecko coins via list snapshot diff.
3. Rank USDT spot pairs by 24h change and realized volatility (1h bars, 24h lookback).
4. Persist scans/events under `data/crypto/market_radar/`.
5. Optional Bark alerts with per-channel cooldown.
6. Vue console: three tabs + config + manual/builtin scan.

## Non-goals (v1)

- Schedules (`job_type`) integration
- Auto-trading or watchlist execution
- Multi-exchange beyond Binance for volatility universe

## APIs

| API | Usage |
|-----|--------|
| Binance spot `exchangeInfo`, `ticker/24hr`, `klines` | Listings diff + vol |
| Binance futures `exchangeInfo` | Perp listings diff |
| CoinGecko `coins/list`, `coins/markets` | Global new coins |

## Default config

| Param | Default |
|-------|---------|
| `top_n_liquidity` | 200 |
| `vol_lookback_hours` | 24 |
| `vol_top_n_compute` | 50 |
| `min_24h_change_pct` | 8.0 |
| `min_realized_vol_pct` | 5.0 |
| `builtin_scan_enabled` | false |
| `builtin_interval_sec` | 600 |
| `alert_cooldown_sec` | 1800 |
| `coingecko_per_page` | 250 |

## Storage

`data/crypto/market_radar/` — `config.json`, `binance_snapshot.json`, `coingecko_snapshot.json`, `scans/`, `events.jsonl`, `alert_state.json`
