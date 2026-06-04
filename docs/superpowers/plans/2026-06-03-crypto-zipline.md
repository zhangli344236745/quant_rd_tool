# Crypto Zipline Strategy Lab — Implementation Plan

> **For agentic workers:** Use subagent-driven-development or executing-plans for task-by-task execution.

**Goal:** Independent crypto backtest lab (option C) with 15m data sync, pandas default engine, optional zipline-reloaded.

**Architecture:** `crypto_zipline_lab` orchestrates ccxt 15m sync + strategy registry + pandas bar backtest; zipline path optional when import succeeds. REST under `/crypto/zipline/*`; UI at `/crypto-zipline`.

**Tech Stack:** FastAPI, pandas, optional zipline-reloaded, Vue 3 + Element Plus

---

### Task 1: Core backend ✅
- `crypto_zipline_pandas.py`, `crypto_zipline_strategies/`, `crypto_zipline_storage.py`, `crypto_zipline_bundle.py`, `crypto_zipline_runner.py`, `crypto_zipline_lab.py`

### Task 2: API routes ✅
- `routes/crypto.py` — sync, backtest, runs, strategies, status

### Task 3: Frontend ✅
- `CryptoZiplineLabView.vue`, router, MainLayout, `api/crypto.ts`

### Task 4: Tests & docs ✅
- `tests/test_crypto_zipline_*.py`, README, `.gitignore` bundles

**Note:** zipline-reloaded conflicts with numpy 2.x in unified venv; `engine=pandas` is production default; `auto` tries zipline then falls back.
