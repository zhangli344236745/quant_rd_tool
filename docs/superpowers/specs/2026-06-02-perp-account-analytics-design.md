# Perp Account Analytics (Balance · Trades · Daily PnL) — Design Spec

**Approved:** 2026-06-02  
**Scope:** Binance USDT-M perpetual (via ccxt + Binance futures endpoints)  
**Delivery:** API + `CryptoOpsView` account panel

## Goals

Provide an ops-facing view for:

1. **Account balances / margin snapshot** (USDT + key assets)
2. **Recent trades** (fills / executions)
3. **Daily PnL** (net = realized PnL + funding + fees), with a small chart + table

## Non-goals (MVP)

- Cross-exchange abstraction beyond Binance futures.
- Full portfolio performance attribution.
- Multi-account / subaccount support.

## Architecture

### Backend

New module: `src/quant_rd_tool/perp_account_analytics.py`

Responsibilities:
- Create authenticated ccxt Binance futures exchange (reuse `ccxt_data.create_exchange`).
- Read-only calls:
  - **Balances**: `ex.fetch_balance({ type: "future" })` fallback to `fapiPrivateV2GetAccount`
  - **Recent trades**: `ex.fetch_my_trades(symbol, since, limit, { type: "future" })`
  - **Daily PnL**: Binance income history endpoint (prefer v1):  
    `fapiPrivateGetIncome({ incomeType, startTime, endTime })` aggregated per day.

### API endpoints

- `GET /api/v1/crypto/perp/account/balances?testnet=false`
- `GET /api/v1/crypto/perp/account/trades?base=ETH&limit=50&testnet=false`
- `GET /api/v1/crypto/perp/account/daily-pnl?days=7&testnet=false`

All endpoints:
- Return friendly `{ enabled: false, error: "missing api key/secret" }` when auth missing.
- Do **not** require kill switch (read-only).

### Frontend

`src/quant_trade_tool/src/views/CryptoOpsView.vue`:
- New section **“账户概览（永续）”**:
  - Stat row: USDT total / available / unrealized pnl
  - Table: balances
  - Table: recent trades (selected base: BTC/ETH)
  - Chart + table: daily pnl (net + breakdown)

## Testing

Unit tests with exchange stubs:
- balances: parses USDT totals
- trades: returns normalized rows
- daily pnl: aggregates by day and by incomeType

