# Polymarket Binary Arbitrage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Polymarket binary YES+NO arbitrage scanner with dual scheduling (built-in + `/schedules`), paper positions, API, and UI under the crypto section.

**Architecture:** Pure HTTP to Gamma + CLOB public endpoints in `crypto_polymarket_arb.py`; scan cycle shared by `crypto_polymarket_scheduler.py`, `PolymarketArbRunner`, and new `scheduler_manager` job type `polymarket_arb`. Follow `crypto_carry_arbitrage.py` patterns for storage and routes.

**Tech Stack:** Python 3.12, FastAPI, httpx (or urllib), Vue 3 + Element Plus, pytest

**Spec:** `docs/superpowers/specs/2026-06-23-polymarket-arb-design.md`

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/quant_rd_tool/crypto_polymarket_arb.py` | Create | Core scan, metrics, paper, persistence |
| `src/quant_rd_tool/crypto_polymarket_scheduler.py` | Create | `run_polymarket_scan_cycle()` |
| `src/quant_rd_tool/crypto_polymarket_runner.py` | Create | Built-in threading timer |
| `src/quant_rd_tool/routes/crypto.py` | Modify | `/polymarket/*` routes |
| `src/quant_rd_tool/scheduler_manager.py` | Modify | `job_type=polymarket_arb` |
| `src/quant_rd_tool/main.py` | Modify | `boot_polymarket_scheduler_if_enabled()` |
| `src/quant_trade_tool/src/api/crypto.ts` | Modify | API client + types |
| `src/quant_trade_tool/src/views/CryptoPolymarketView.vue` | Create | UI |
| `src/quant_trade_tool/src/router/index.ts` | Modify | Route |
| `src/quant_trade_tool/src/layouts/MainLayout.vue` | Modify | Nav item |
| `tests/fixtures/polymarket_*.json` | Create | HTTP mocks |
| `tests/test_crypto_polymarket_*.py` | Create | Unit + route + scheduler tests |

---

### Task 1: Edge calculation & config (pure functions)

**Files:**
- Create: `src/quant_rd_tool/crypto_polymarket_arb.py`
- Create: `tests/test_crypto_polymarket_arb.py`
- Create: `tests/fixtures/polymarket_clob_book.json`

- [ ] **Step 1: Write failing tests for `compute_binary_edge`**

```python
def test_compute_binary_edge_positive():
    from quant_rd_tool.crypto_polymarket_arb import compute_binary_edge, PolymarketArbConfig
    cfg = PolymarketArbConfig(taker_fee_bps=200)
    r = compute_binary_edge(ask_yes=0.45, ask_no=0.50, ask_yes_size=100, ask_no_size=80, config=cfg)
    assert r["edge_bps"] > 0
    assert r["size_cap"] == 80
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/test_crypto_polymarket_arb.py::test_compute_binary_edge_positive -v`

- [ ] **Step 3: Implement `PolymarketArbConfig`, `compute_binary_edge`, `merge_market_universe`**

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_crypto_polymarket_arb.py -v`

---

### Task 2: HTTP client & scan (mocked)

**Files:**
- Modify: `src/quant_rd_tool/crypto_polymarket_arb.py`
- Create: `tests/fixtures/polymarket_gamma_markets.json`
- Modify: `tests/test_crypto_polymarket_arb.py`

- [ ] **Step 1: Write test `test_scan_markets_from_fixtures` with monkeypatched `fetch_gamma_markets` / `fetch_clob_book`**

- [ ] **Step 2: Implement `fetch_gamma_markets`, `fetch_clob_book`, `scan_markets`, `save_scan_snapshot`**

Storage dir: `POLYMARKET_DIR = Path("data/crypto/polymarket")`

- [ ] **Step 3: Test watchlist + top_n merge dedupes by `condition_id`**

- [ ] **Step 4: Run `uv run pytest tests/test_crypto_polymarket_arb.py -v`**

---

### Task 3: Paper positions & events

**Files:**
- Modify: `src/quant_rd_tool/crypto_polymarket_arb.py`
- Modify: `tests/test_crypto_polymarket_arb.py`

- [ ] **Step 1: Test `open_paper_position` / `close_paper_position` PnL**

- [ ] **Step 2: Implement position JSON under `positions/`, append `events.jsonl`**

- [ ] **Step 3: Enforce one open position per `condition_id`**

- [ ] **Step 4: Run tests**

---

### Task 4: Scan cycle & dedupe

**Files:**
- Create: `src/quant_rd_tool/crypto_polymarket_scheduler.py`
- Create: `tests/test_crypto_polymarket_scheduler.py`

- [ ] **Step 1: Test `run_polymarket_scan_cycle` writes `scans/{ts}.json` and appends opportunities**

- [ ] **Step 2: Implement cycle with `scan_dedupe_sec` guard on `last_scan_at` in config/state**

- [ ] **Step 3: Hook `evaluate_polymarket_alerts` (Bark/webhook via `schedule_alerts` or lightweight local cooldown)**

- [ ] **Step 4: Run tests**

---

### Task 5: Built-in runner

**Files:**
- Create: `src/quant_rd_tool/crypto_polymarket_runner.py`
- Modify: `src/quant_rd_tool/main.py`

- [ ] **Step 1: Implement `PolymarketArbRunner` (mirror `HftRunnerManager` simplicity — single global scan thread)**

- [ ] **Step 2: `boot_polymarket_scheduler_if_enabled()` reads config `builtin_scan_enabled`**

- [ ] **Step 3: Manual smoke: start/stop via future API**

---

### Task 6: API routes

**Files:**
- Modify: `src/quant_rd_tool/routes/crypto.py`
- Create: `tests/test_crypto_polymarket_routes.py`

- [ ] **Step 1: Add Pydantic models + routes per spec (`/polymarket/scan`, `/config`, `/positions`, `/builtin/*`)**

- [ ] **Step 2: Route tests with `TestClient` + monkeypatch scan dir**

Run: `uv run pytest tests/test_crypto_polymarket_routes.py -v`

---

### Task 7: Schedules integration

**Files:**
- Modify: `src/quant_rd_tool/scheduler_manager.py`
- Modify: `src/quant_trade_tool/src/views/SchedulesView.vue` (if job_type dropdown is hardcoded)

- [ ] **Step 1: Extend `JobType` with `polymarket_arb`**

- [ ] **Step 2: In `_run_job_cycle`, branch to `run_polymarket_scan_cycle()`**

- [ ] **Step 3: Set `last_cycle_summary` fields: `opportunities_count`, `best_edge_bps`, `markets_scanned`**

- [ ] **Step 4: Test schedule job run-once via existing schedule test pattern or new test**

---

### Task 8: Frontend

**Files:**
- Modify: `src/quant_trade_tool/src/api/crypto.ts`
- Create: `src/quant_trade_tool/src/views/CryptoPolymarketView.vue`
- Modify: `src/quant_trade_tool/src/router/index.ts`
- Modify: `src/quant_trade_tool/src/layouts/MainLayout.vue`

- [ ] **Step 1: Add `cryptoApi.polymarket*` methods and TypeScript interfaces**

- [ ] **Step 2: Build view: scan table, config, paper positions, builtin toggle**

- [ ] **Step 3: Router + nav 「Polymarket 套利」**

- [ ] **Step 4: `npm run build` in `src/quant_trade_tool`**

---

### Task 9: Verification

- [ ] **Run full test suite for new modules**

Run: `uv run pytest tests/test_crypto_polymarket*.py -v`

- [ ] **Run broader crypto tests (no regressions)**

Run: `uv run pytest tests/test_crypto_carry*.py tests/test_schedule_alerts.py -q`

- [ ] **Manual:** `uv run quant-rd serve` → open `/crypto-polymarket` → scan → verify table

---

## Notes for implementer

- Use `httpx` if already in project; else `urllib.request` to avoid new deps (check `pyproject.toml`).
- Gamma market shape varies; normalize to `{condition_id, question, yes_token_id, no_token_id, volume24hr}`.
- CLOB book: asks sorted ascending; best ask = `asks[0]`.
- Carry reference: `crypto_carry_arbitrage.py` lines 1–200 for config/load/save patterns.
- Do not commit `data/crypto/polymarket/` artifacts.
