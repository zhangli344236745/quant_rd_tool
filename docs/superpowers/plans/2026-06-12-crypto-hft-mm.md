# Crypto Market Making (HFT v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship standalone REST-polling live market-making for Binance spot + USDT-M perp (testnet default), classic + grid strategies, API + Vue UI.

**Architecture:** `crypto_hft_runner` loops → `crypto_hft.run_cycle` fetches book/open orders → `crypto_hft_strategies.build_quotes` → cancel-replace limit post-only orders; state/events under `data/crypto/hft/`. Parallel to carry module.

**Tech Stack:** Python 3.11+, FastAPI, ccxt, Vue 3 + Element Plus

**Spec:** [docs/superpowers/specs/2026-06-12-crypto-hft-mm-design.md](../specs/2026-06-12-crypto-hft-mm-design.md)

---

## File map

| Action | Path | Role |
|--------|------|------|
| Create | `crypto_hft_strategies.py` | classic_mm + grid_mm |
| Create | `crypto_hft_storage.py` | config/state/events |
| Create | `crypto_hft.py` | book, reconcile, cycle |
| Create | `crypto_hft_runner.py` | per-bot threads |
| Create | `routes/crypto_hft.py` | REST API |
| Modify | `routes/__init__.py` | register router |
| Create | `tests/test_crypto_hft_strategies.py` | strategy tests |
| Create | `tests/test_crypto_hft.py` | engine tests |
| Create | `tests/test_crypto_hft_routes.py` | API tests |
| Create | `tests/fixtures/hft_book.json` | synthetic book |
| Modify | `api/crypto.ts` | hft types + methods |
| Create | `views/CryptoHftView.vue` | UI |
| Modify | `router/index.ts`, `MainLayout.vue` | route + nav |

---

### Task 1: Strategies + storage

- [ ] Tests for `build_quotes` (classic skew, grid levels)
- [ ] `crypto_hft_strategies.py`, `crypto_hft_storage.py`

### Task 2: Engine + runner

- [ ] Tests for order diff / kill switch skip
- [ ] `crypto_hft.py`, `crypto_hft_runner.py`

### Task 3: API

- [ ] `routes/crypto_hft.py` + router registration
- [ ] `tests/test_crypto_hft_routes.py`

### Task 4: Frontend

- [ ] `crypto.ts` + `CryptoHftView.vue` + router/nav
- [ ] `npm run build`

### Task 5: Verification

- [ ] `pytest tests/test_crypto_hft_* -v`
