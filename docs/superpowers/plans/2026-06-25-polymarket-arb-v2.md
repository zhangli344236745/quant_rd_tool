# Polymarket Arbitrage v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Polymarket scanner with reliable market filtering, depth-aware metrics, three arbitrage strategies, analytics APIs, and enhanced UI—paper trading remains `binary_ask` only.

**Architecture:** Extract `crypto_polymarket_scanner.py` (Gamma filter + CLOB + depth walk), `crypto_polymarket_strategies.py` (binary_ask/bid, multi_ask), `crypto_polymarket_analytics.py` (edge history/trend/leaderboard). `crypto_polymarket_arb.py` orchestrates scan, persists results, keeps paper positions. Frontend extends `CryptoPolymarketView.vue`.

**Tech Stack:** Python 3.12, FastAPI, httpx, Vue 3 + Element Plus, pytest

**Spec:** `docs/superpowers/specs/2026-06-25-polymarket-arb-v2-design.md`

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/quant_rd_tool/crypto_polymarket_scanner.py` | Create | Filter, book fetch, depth walk |
| `src/quant_rd_tool/crypto_polymarket_strategies.py` | Create | Strategy evaluators |
| `src/quant_rd_tool/crypto_polymarket_analytics.py` | Create | Edge history, trend, leaderboard |
| `src/quant_rd_tool/crypto_polymarket_arb.py` | Modify | Config v2 fields, orchestrate scan, analytics hooks |
| `src/quant_rd_tool/routes/crypto.py` | Modify | Analytics routes, extended scan response |
| `src/quant_trade_tool/src/api/crypto.ts` | Modify | Types + analytics API |
| `src/quant_trade_tool/src/views/CryptoPolymarketView.vue` | Modify | Tabs, depth expand, sparkline, leaderboard |
| `tests/fixtures/polymarket_clob_book_deep.json` | Create | Multi-level ask ladder |
| `tests/fixtures/polymarket_gamma_multi_outcome.json` | Create | 3+ outcome market |
| `tests/test_crypto_polymarket_scanner.py` | Create | Filter + depth tests |
| `tests/test_crypto_polymarket_strategies.py` | Create | Strategy tests |
| `tests/test_crypto_polymarket_analytics.py` | Create | Analytics tests |
| `tests/test_crypto_polymarket_arb.py` | Modify | v2 scan integration |
| `tests/test_crypto_polymarket_routes.py` | Modify | Analytics route tests |

---

## Phase 1: Market filter + book status

### Task 1: Market filter pure functions

**Files:**
- Create: `src/quant_rd_tool/crypto_polymarket_scanner.py`
- Create: `tests/test_crypto_polymarket_scanner.py`

- [ ] **Step 1: Write failing tests for `passes_market_filter`**

```python
def test_passes_market_filter_rejects_updown_slug():
    from quant_rd_tool.crypto_polymarket_scanner import passes_market_filter, MarketFilterConfig
    cfg = MarketFilterConfig(min_volume24hr_usd=1000, exclude_slug_patterns=["*-updown-*"])
    m = {"slug": "eth-updown-5m-123", "volume24hr": 99999, "acceptingOrders": True}
    assert passes_market_filter(m, cfg) is False

def test_passes_market_filter_accepts_normal_market():
    from quant_rd_tool.crypto_polymarket_scanner import passes_market_filter, MarketFilterConfig
    cfg = MarketFilterConfig(min_volume24hr_usd=5000)
    m = {"slug": "btc-100k-2026", "volume24hr": 50000, "acceptingOrders": True}
    assert passes_market_filter(m, cfg) is True
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/test_crypto_polymarket_scanner.py::test_passes_market_filter_rejects_updown_slug -v`

- [ ] **Step 3: Implement `MarketFilterConfig`, `passes_market_filter`, `filter_markets`**

Use `fnmatch.fnmatch` for slug patterns.

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_crypto_polymarket_scanner.py -v -k filter`

---

### Task 2: Book status classification

**Files:**
- Modify: `src/quant_rd_tool/crypto_polymarket_scanner.py`
- Modify: `tests/test_crypto_polymarket_scanner.py`

- [ ] **Step 1: Write test `classify_book_error` — 404 → `no_book`, other → `error`**

- [ ] **Step 2: Implement `BookStatus` literal and `classify_book_error(exc)`**

- [ ] **Step 3: Refactor `fetch_clob_book_safe` returning `{book, status, error}`**

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_crypto_polymarket_scanner.py -v`

---

### Task 3: Wire filter into scan pipeline

**Files:**
- Modify: `src/quant_rd_tool/crypto_polymarket_arb.py`
- Modify: `src/quant_rd_tool/crypto_polymarket_arb.py` — extend `PolymarketArbConfig`
- Modify: `tests/test_crypto_polymarket_arb.py`

- [ ] **Step 1: Add v2 config fields to `PolymarketArbConfig` + `load_config`/`save_config`**

- [ ] **Step 2: In `scan_markets`, apply `filter_markets` before book fetch**

- [ ] **Step 3: Update scan payload: `markets_skipped`, `markets_errors`, `markets_scanned_ok`**

- [ ] **Step 4: Test scan with monkeypatched gamma returning updown + valid markets**

Run: `uv run pytest tests/test_crypto_polymarket_arb.py -v`

---

## Phase 2: Depth walk + depth metrics

### Task 4: Depth walk

**Files:**
- Modify: `src/quant_rd_tool/crypto_polymarket_scanner.py`
- Create: `tests/fixtures/polymarket_clob_book_deep.json`
- Modify: `tests/test_crypto_polymarket_scanner.py`

- [ ] **Step 1: Write failing test `test_walk_ask_ladder_vwap`**

```python
def test_walk_ask_ladder_vwap():
    from quant_rd_tool.crypto_polymarket_scanner import walk_ask_ladder
    book = json.loads(Path("tests/fixtures/polymarket_clob_book_deep.json").read_text())
    r = walk_ask_ladder(book, target_shares=100, max_levels=10)
    assert r["filled_shares"] == 100
    assert 0 < r["vwap"] < 1
    assert len(r["ladder"]) >= 2
```

- [ ] **Step 2: Implement `walk_ask_ladder` and `walk_bid_ladder`**

- [ ] **Step 3: Implement `walk_binary_depth(yes_book, no_book, target, max_levels)`**

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_crypto_polymarket_scanner.py -v -k walk`

---

### Task 5: Depth-aware binary_ask metrics

**Files:**
- Create: `src/quant_rd_tool/crypto_polymarket_strategies.py`
- Create: `tests/test_crypto_polymarket_strategies.py`
- Modify: `src/quant_rd_tool/crypto_polymarket_arb.py`

- [ ] **Step 1: Move `compute_binary_edge` to strategies or wrap with `eval_binary_ask(depth_result, config)`**

- [ ] **Step 2: Test depth edge lower than top-of-book when slippage exists**

- [ ] **Step 3: Update `scan_market_row` to attach `depth_*` fields and `strategy_type=binary_ask`**

- [ ] **Step 4: Update `preview_paper_open` to use VWAP when depth available**

Run: `uv run pytest tests/test_crypto_polymarket_strategies.py tests/test_crypto_polymarket_arb.py -v`

---

## Phase 3: binary_bid + multi_ask

### Task 6: binary_bid strategy

**Files:**
- Modify: `src/quant_rd_tool/crypto_polymarket_strategies.py`
- Modify: `tests/test_crypto_polymarket_strategies.py`

- [ ] **Step 1: Test `eval_binary_bid` — bids summing > 1 minus fees → positive edge**

- [ ] **Step 2: Implement using `walk_bid_ladder` on both books**

- [ ] **Step 3: Integrate in scan when `binary_bid` in `enabled_strategies`**

---

### Task 7: multi_ask strategy

**Files:**
- Create: `tests/fixtures/polymarket_gamma_multi_outcome.json`
- Modify: `src/quant_rd_tool/crypto_polymarket_arb.py` — `normalize_gamma_market` for N tokens
- Modify: `src/quant_rd_tool/crypto_polymarket_strategies.py`

- [ ] **Step 1: Extend `normalize_gamma_market` → `token_ids: list[str]`, `outcome_count`**

- [ ] **Step 2: Test `eval_multi_ask` with 3-outcome fixture books**

- [ ] **Step 3: Scan loop fetches N books for multi markets; emit row per strategy match**

- [ ] **Step 4: Add `strategy_counts` to scan payload**

Run: `uv run pytest tests/test_crypto_polymarket_strategies.py -v`

---

## Phase 4: Analytics + API + UI

### Task 8: Edge history & analytics

**Files:**
- Create: `src/quant_rd_tool/crypto_polymarket_analytics.py`
- Create: `tests/test_crypto_polymarket_analytics.py`
- Modify: `src/quant_rd_tool/crypto_polymarket_arb.py`

- [ ] **Step 1: Test `append_edge_history` + `edge_trend(condition_id, hours)`**

- [ ] **Step 2: Implement `leaderboard(hours, limit)` aggregating hit count + max edge**

- [ ] **Step 3: Call `append_edge_history` from scan when `opportunity=true`**

---

### Task 9: API routes

**Files:**
- Modify: `src/quant_rd_tool/routes/crypto.py`
- Modify: `tests/test_crypto_polymarket_routes.py`

- [ ] **Step 1: Add `GET /polymarket/analytics/edge-trend`**

- [ ] **Step 2: Add `GET /polymarket/analytics/leaderboard`**

- [ ] **Step 3: Route tests with temp polymarket dir**

Run: `uv run pytest tests/test_crypto_polymarket_routes.py -v`

---

### Task 10: Frontend

**Files:**
- Modify: `src/quant_trade_tool/src/api/crypto.ts`
- Modify: `src/quant_trade_tool/src/views/CryptoPolymarketView.vue`

- [ ] **Step 1: Add TypeScript types for v2 fields + analytics API methods**

- [ ] **Step 2: Strategy filter tabs on opportunity table**

- [ ] **Step 3: Scan health stats row (`markets_scanned_ok` / skipped / errors)**

- [ ] **Step 4: Expandable row with depth ladder + profit banner**

- [ ] **Step 5: Leaderboard card + edge sparkline (simple SVG polyline or Element Plus chart)**

- [ ] **Step 6: Hide paper-open button unless `strategy_type === 'binary_ask'`**

- [ ] **Step 7: `npm run build` in `src/quant_trade_tool`**

---

### Task 11: Verification

- [ ] **Run all polymarket tests**

Run: `uv run pytest tests/test_crypto_polymarket*.py -v`

- [ ] **Manual smoke: `uv run quant-rd serve` → scan → verify non-zero `markets_scanned_ok` and strategy tabs**

- [ ] **Restart server if already running to pick up backend changes**

---

## Notes for implementer

- Keep backward compat: old `config.json` without v2 fields uses defaults from spec.
- `httpx.HTTPStatusError` with `response.status_code == 404` → `no_book`, not `error`.
- Gamma field casing varies: check `acceptingOrders`, `accepting_orders`.
- Carry UI reference: `CryptoCarryView.vue` profit banners and expand rows.
- Do not commit `data/crypto/polymarket/` runtime artifacts.
- `crypto_polymarket_arb.py` is large; move new logic to scanner/strategies/analytics rather than growing it further.
