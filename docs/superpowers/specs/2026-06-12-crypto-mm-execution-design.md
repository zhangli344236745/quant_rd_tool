# Crypto MM Execution Layer — Design (2026-06-12)

**Scope:** Shared execution improvements for REST + WS market making.

## Features

| Feature | Description |
|---------|-------------|
| Tag reconcile | `clientOrderId` = `mm-{bot}-{tag}`; match before price tolerance |
| Fee-aware quotes | Widen to `maker_fee_bps + min_edge_bps` min half-spread; reject crossing BBO |
| Batch cancel | Prefer `cancel_orders` API with sequential fallback |
| WS reconnect | On transient connection errors, close exchange and reconnect |
| Execution stats | `placed`, `canceled`, `rejected_cross`, `fee_adjusted`, `batch_cancel_used`, `reconnects` |

## Module

`crypto_hft_execution.py` — used by `crypto_hft.py` and `crypto_ws_hft.py`.

## Config (both REST/WS bots)

- `maker_fee_bps` default 2.0
- `min_edge_bps` default 1.0
- `use_client_order_tags` default true
- `batch_cancel` default true
