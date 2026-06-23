# Crypto WebSocket Market Making — Implementation Plan

**Goal:** Standalone ccxt.pro WebSocket event-driven market making (dry_run default), parallel to REST HFT.

**Spec:** [docs/superpowers/specs/2026-06-12-crypto-ws-hft-design.md](../specs/2026-06-12-crypto-ws-hft-design.md)

## File map

| Action | Path |
|--------|------|
| Create | `crypto_hft_common.py` |
| Create | `crypto_ws_hft_storage.py` |
| Create | `crypto_ws_hft.py` |
| Create | `crypto_ws_hft_runner.py` |
| Create | `routes/crypto_ws_hft.py` |
| Modify | `routes/__init__.py` |
| Create | `tests/test_crypto_hft_common.py` |
| Create | `tests/test_crypto_ws_hft.py` |
| Create | `tests/test_crypto_ws_hft_routes.py` |
| Modify | `api/crypto.ts`, `CryptoWsHftView.vue`, router, nav |

## Tasks

### Task 1: Common + storage + unit tests
### Task 2: Async engine + runner
### Task 3: API routes
### Task 4: Frontend
### Task 5: `pytest tests/test_crypto_*ws* tests/test_crypto_hft_common.py -v` + `npm run build`
