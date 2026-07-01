# Polymarket v3 — Workflow Linkage, Backtest Analytics & Real-Time Cross-Venue

**Approved:** 2026-06-12  
**Scope:** B + C + D (Kalshi crypto-themed only)  
**Delivery:** Phased — v3.1 (C) → v3.2 (B) → v3.3 (D)  
**Builds on:** `docs/superpowers/specs/2026-06-25-polymarket-arb-v2-design.md`

## User decisions

| Dimension | Choice |
|-----------|--------|
| Priority pillars | B 研判联动 + C 分析回测 + D 实时与覆盖 |
| Delivery order | **方案 1 数据先行**：C → B → D |
| Kalshi scope | **A — crypto 主题市场 only**（BTC/ETH/SOL 等，与 Workflow 标的一一对应） |
| Live trading | Still out of scope (no `py-clob-client`, no wallet) |

## Problem statement

Polymarket v2 is a capable **standalone arb scanner** but remains disconnected from the rest of the crypto stack:

1. **No Workflow linkage** — spot/ML/options advice ignores prediction-market implied probabilities.
2. **Weak analytics** — Advisor win rates are heuristic; no ROI backtest or tier calibration from historical hits / paper closes.
3. **Polling-only books** — REST scan interval misses short-lived edges; no cross-venue view vs Kalshi on the same crypto questions.

## Goals

### v3.1 — Backtest & Advisor calibration (C)

1. Aggregate `opportunities.jsonl`, `edge_history.jsonl`, paper positions, and Gamma resolution status into backtest reports.
2. Expose strategy comparison and advisor calibration APIs.
3. Replace heuristic-only `persistence_rate` with calibrated weights where data exists.
4. UI tab「回测分析」with strategy compare + calibration table.

### v3.2 — Crypto Workflow linkage (B)

1. New workflow step `polymarket_context` matching symbol → Polymarket crypto-themed markets.
2. `crypto_polymarket_integration.py` cross-view (spot stance × implied probability), mirroring `crypto_options_integration.py`.
3. Extend `synthesize_advice` with **prediction** segment (or bullets in spot segment — see below).
4. Default template includes optional `polymarket_context` step.

### v3.3 — Real-time & Kalshi cross-venue (D)

1. Optional WebSocket book cache for watchlist / crypto-universe markets; debounced rescan.
2. Expanded Gamma filters: `crypto_symbol_keywords` map per base asset.
3. Kalshi REST read-only module; match crypto-themed Poly ↔ Kalshi pairs; show `prob_spread_bps`.
4. UI: cross-venue column + detail drawer; stream mode in config.

## Non-goals

- Live order placement on Polymarket or Kalshi
- Full-market fuzzy Kalshi matching (non-crypto events)
- Auto paper open on arb threshold
- Paper trading for `binary_bid` / `multi_ask` (unchanged from v2)

---

## Phase v3.1 — Backtest analytics (C)

### Module: `crypto_polymarket_backtest.py`

| Function | Purpose |
|----------|---------|
| `load_opportunity_history(hours)` | Read `opportunities.jsonl` with time filter |
| `load_paper_outcomes()` | Join open/closed positions with settlement |
| `build_strategy_backtest(hours)` | Per-strategy hit count, avg edge, avg profit_at_size, fill rate |
| `build_roi_distribution(hours)` | Histogram buckets for paper PnL % and edge_bps |
| `build_advisor_calibration(hours)` | Group by recommendation tier → actual paper win rate |
| `resolve_market_outcome(condition_id)` | Gamma fetch `closed` + winning outcome (cached) |

### Data sources

| Path | Use |
|------|-----|
| `data/crypto/polymarket/opportunities.jsonl` | Opportunity frequency, edge stats |
| `data/crypto/polymarket/edge_history.jsonl` | Persistence / decay |
| `data/crypto/polymarket/positions/*.json` | Realized paper PnL |
| `data/crypto/polymarket/scans/*.json` | Scan health over time |
| Gamma `GET /markets?condition_id=` | Resolution / settlement for calibration |

### New API routes

| Method | Path | Query | Response |
|--------|------|-------|----------|
| GET | `/crypto/polymarket/analytics/backtest` | `hours=168` | `{strategies: [...], summary: {...}}` |
| GET | `/crypto/polymarket/analytics/roi-distribution` | `hours=168`, `strategy_type?` | `{buckets: [...], n}` |
| GET | `/crypto/polymarket/analytics/advisor-calibration` | `hours=720` | `{tiers: [{level, predicted_wr, actual_wr, n}]}` |
| GET | `/crypto/polymarket/analytics/strategy-compare` | `hours=168` | Alias/summary of backtest for charts |

### Advisor changes (`crypto_polymarket_advisor.py`)

```python
# persistence_rate: blend heuristic + calibrated tier prior when n >= 5 paper closes
calibrated_wr = calibration_lookup(strategy_type, edge_bucket)
composite = certainty * 0.35 + persist * 0.25 + execution * 0.25 + calibrated_wr * 0.15
```

Fallback to v2 heuristic when calibration sample insufficient.

### Frontend (v3.1)

- `CryptoPolymarketView.vue`: new tab **回测分析**
  - Strategy compare bar chart (hit count, avg edge_at_size_bps, avg profit)
  - ROI distribution (simple bucket table or inline bars)
  - Advisor calibration table (tier / predicted / actual / sample n)
- `crypto.ts`: types + API methods for four endpoints

### Tests

- `tests/test_crypto_polymarket_backtest.py` — aggregation, empty history, fixture JSONL
- Extend `test_crypto_polymarket_routes.py` — new analytics routes
- Extend `test_crypto_polymarket_advisor.py` — calibrated persistence when fixture present

---

## Phase v3.2 — Workflow linkage (B)

### Symbol → market matching

**Module:** `crypto_polymarket_context.py`

```python
CRYPTO_SYMBOL_KEYWORDS: dict[str, list[str]] = {
    "BTC": ["bitcoin", "btc", "100k", "150k", "halving"],
    "ETH": ["ethereum", "eth", "etf"],
    "SOL": ["solana", "sol"],
    "BNB": ["bnb", "binance"],
}
```

**Matching pipeline:**

1. Load latest scan items OR run lightweight Gamma query filtered by slug/question keywords.
2. Score markets: keyword hits + volume24hr + not excluded slug patterns.
3. Pick `top_market` (highest score) and up to `max_markets=5` related rows.
4. Derive `implied_prob_yes` from mid of YES token (best bid/ask average) or VWAP if book available.

### Workflow step

Add to `STEP_CATALOG`:

```python
{
    "id": "polymarket_context",
    "name": "预测市场",
    "description": "Polymarket crypto 主题市场隐含概率与套利摘要",
    "params_schema": {
        "max_markets": {"type": "integer", "default": 5},
        "include_arb_summary": {"type": "boolean", "default": True},
    },
}
```

Handler `_step_polymarket_context(ctx, params)` → calls `fetch_polymarket_context(symbol, data_dir=...)`.

**Output shape:**

```json
{
  "enabled": true,
  "base": "BTC",
  "market_count": 3,
  "top_market": {
    "condition_id": "...",
    "question": "...",
    "implied_prob_yes": 0.62,
    "volume24hr": 120000,
    "end_date": "..."
  },
  "markets": [...],
  "arb_summary": {"binary_ask_hits": 1, "best_edge_bps": 45},
  "cross_view": {...}
}
```

### Cross-view (`crypto_polymarket_integration.py`)

Mirror `synthesize_cross_market_view` from options:

| Spot stance | Implied prob | Alignment | Summary intent |
|-------------|--------------|-----------|----------------|
| 看涨 | rising / high (>0.6) | 共振 | 现货与预测市场同向偏多 |
| 看涨 | falling / low (<0.4) | 分歧 | 技术面偏多但市场定价偏空 |
| 看跌 | low | 共振 | 偏空共振 |
| 中性 | any | 补充 | 方向不明，参考隐含概率事件风险 |

### Advice synthesis

Add `_synthesize_prediction_advice(...)` → new segment **`prediction`** in `segments`:

```json
"segments": {
  "spot": {...},
  "perp": {...},
  "options": {...},
  "prediction": {
    "segment": "prediction",
    "label": "预测市场",
    "stance": "偏多/偏空/中性/不可用",
    "headline": "BTC 预测市场：...",
    "bullets": [...],
    "advice": "..."
  }
}
```

`CryptoWorkflowView.vue`: fourth tab **预测市场** in 分市场建议.

### Tests

- `tests/test_crypto_polymarket_context.py` — keyword matching, implied prob
- `tests/test_crypto_polymarket_integration.py` — cross_view rules
- Extend `test_crypto_workflow.py` — step in catalog, segments.prediction

---

## Phase v3.3 — Real-time & Kalshi (D)

### Polymarket WebSocket — `crypto_polymarket_stream.py`

- Connect to Polymarket CLOB WebSocket (market channel) for token IDs in watchlist + crypto universe.
- Maintain in-memory L2 cache `{token_id: book}`.
- On update: set dirty flag; `PolymarketArbRunner` debounces full scan (default **2s**).
- Config: `stream_mode: "rest" | "websocket" | "hybrid"` (default `rest` for backward compat).

### Crypto universe filters

Extend `PolymarketArbConfig`:

| Param | Default | Description |
|-------|---------|-------------|
| `crypto_universe_enabled` | `false` | When true, merge keyword-filtered markets into scan universe |
| `crypto_symbol_keywords` | see v3.2 map | Override per-symbol keywords |
| `stream_mode` | `"rest"` | Book feed mode |
| `stream_debounce_s` | `2.0` | Min seconds between WS-triggered scans |

### Kalshi — crypto-themed only

**Module:** `crypto_kalshi_data.py`

- Base URL: `https://external-api.kalshi.com/trade-api/v2`
- `fetch_crypto_markets(base: str)` — filter markets where title/subtitle matches `CRYPTO_SYMBOL_KEYWORDS[base]`
- `fetch_orderbook(ticker)` — public, no auth

**Module:** `crypto_polymarket_cross_venue.py`

- `match_crypto_pair(poly_market, kalshi_markets)` — require **same base symbol** + keyword overlap score ≥ threshold (default 0.6)
- `compare_implied_prob(poly_yes, kalshi_yes)` → `prob_spread_bps`, `arb_hint` (research text only)

**Storage:** append cross-venue hits to `cross_venue_history.jsonl`.

### New API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/crypto/polymarket/cross-venue` | `?base=BTC` → matched pairs with spread |
| GET | `/crypto/polymarket/stream/status` | WS connection health |

### Frontend (v3.3)

- Config form: `stream_mode`, `crypto_universe_enabled`
- Opportunity table column **跨所价差** (when Kalshi match exists)
- Expand row: Poly vs Kalshi implied prob side-by-side
- Stream status indicator on scan health bar

### Tests

- `tests/test_crypto_kalshi_data.py` — mock REST responses
- `tests/test_crypto_polymarket_cross_venue.py` — matching threshold, spread calc
- `tests/test_crypto_polymarket_stream.py` — debounce logic with mock messages (no live WS in CI)

---

## Module layout (final)

| Module | Phase | Responsibility |
|--------|-------|----------------|
| `crypto_polymarket_backtest.py` | 3.1 | Historical ROI, calibration |
| `crypto_polymarket_context.py` | 3.2 | Symbol→market fetch for Workflow |
| `crypto_polymarket_integration.py` | 3.2 | Cross-view + advice helpers |
| `crypto_polymarket_stream.py` | 3.3 | WS book cache + debounce |
| `crypto_kalshi_data.py` | 3.3 | Kalshi public REST |
| `crypto_polymarket_cross_venue.py` | 3.3 | Crypto-themed pair matching |
| Existing arb/scanner/strategies/advisor | all | Orchestration unchanged; advisor consumes calibration |

---

## Error handling

- Gamma/Kalshi down: Workflow step returns `enabled: false` with reason; advice segment shows 不可用
- Empty backtest history: APIs return `{items: [], n: 0}` not 404
- WS disconnect: runner falls back to REST interval scan; `stream/status` shows `degraded`
- No Kalshi match: omit cross-venue fields; no error

---

## Security

- Read-only public APIs; no trading keys
- Disclaimers unchanged: research / paper only
- Kalshi + Polymarket links open external URLs only

---

## Phased delivery checklist

| Phase | Deliverable | Exit criteria |
|-------|-------------|---------------|
| **v3.1** | Backtest module + 4 APIs + UI tab + advisor calibration | Tests green; calibration table renders with fixture data |
| **v3.2** | Workflow step + integration + prediction segment | BTC workflow run shows prediction tab with implied prob |
| **v3.3** | WS stream + Kalshi cross-venue + UI columns | Mock tests green; manual smoke on BTC cross-venue row |

---

## Out of scope (v4+)

- `py-clob-client` live execution
- Full Kalshi universe fuzzy matching
- Auto paper open
- WebSocket on Kalshi (REST poll sufficient for v3.3 crypto subset)
