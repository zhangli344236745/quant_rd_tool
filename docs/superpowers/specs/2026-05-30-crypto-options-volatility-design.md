# Crypto Options Volatility Watch — Design Spec

**Approved:** 2026-05-30  
**Data source:** Binance Options (EAPI)  
**Delivery:** API + CLI + Vue console page (`C`)

## Goals

Detect underlyings with **elevated options volatility** using:

1. **IV percentile** (30-day lookback, default alert ≥ 80)
2. **IV 24h change** (default alert ≥ +10%)
3. **Cross-symbol rank** (composite score across BTC, ETH, SOL, BNB)

Provide **rule-based investment suggestions** (research only, not licensed advice).

## Architecture

| Module | Responsibility |
|--------|----------------|
| `crypto_options_data.py` | Binance EAPI fetch, ATM IV pick, JSONL snapshots |
| `crypto_options_vol_scan.py` | Percentile, change, rank, alert levels |
| `crypto_options_advisor.py` | Narrative + actions from scan rows |
| `routes/crypto.py` | REST endpoints |
| `cli.py` | `crypto options-scan` |
| `CryptoOptionsVolView.vue` | Console UI |

Local history: `data/crypto/options_iv/{BASE}.jsonl`

## API

- `GET /api/v1/crypto/options/volatility-scan`
- `GET /api/v1/crypto/options/volatility-scan/config`
- `POST /api/v1/crypto/options/volatility-scan/config`
- `GET /api/v1/crypto/options/volatility-scan/history?symbol=BTC`

## Non-goals (MVP)

Auto-trading, full vol surface, Deribit, multi-exchange.
