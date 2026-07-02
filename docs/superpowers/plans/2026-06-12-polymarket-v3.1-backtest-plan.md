# Polymarket v3.1 Backtest Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add historical backtest analytics, advisor calibration APIs, and a「回测分析」UI tab for Polymarket.

**Architecture:** New `crypto_polymarket_backtest.py` reads local JSONL + position files; four REST routes under existing `/polymarket/analytics/*`; advisor blends calibrated tier priors when sample size sufficient.

**Tech Stack:** Python 3.11+, FastAPI, Vue 3 + Element Plus, pytest.

**Spec:** `docs/superpowers/specs/2026-06-12-polymarket-v3-design.md` (Phase v3.1)

---

### Task 1: Backtest module + unit tests

**Files:**
- Create: `src/quant_rd_tool/crypto_polymarket_backtest.py`
- Create: `tests/test_crypto_polymarket_backtest.py`
- Create: `tests/fixtures/polymarket_opportunities_sample.jsonl`

- [ ] Implement `load_opportunity_history`, `build_strategy_backtest`, `build_roi_distribution`, `build_advisor_calibration`
- [ ] Tests with tmp_path fixtures

### Task 2: API routes

**Files:**
- Modify: `src/quant_rd_tool/routes/crypto.py`
- Modify: `tests/test_crypto_polymarket_routes.py`

- [ ] Add 4 GET routes: backtest, roi-distribution, advisor-calibration, strategy-compare

### Task 3: Advisor calibration blend

**Files:**
- Modify: `src/quant_rd_tool/crypto_polymarket_advisor.py`
- Modify: `tests/test_crypto_polymarket_advisor.py`

- [ ] Add `calibration_prior()`; update `estimate_win_rate` weights when n≥5

### Task 4: Frontend

**Files:**
- Modify: `src/quant_trade_tool/src/api/crypto.ts`
- Modify: `src/quant_trade_tool/src/views/CryptoPolymarketView.vue`

- [ ] Types + API methods; new main tab「回测分析」with strategy table + calibration table
