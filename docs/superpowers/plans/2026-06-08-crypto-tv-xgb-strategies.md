# Crypto TV 50 策略 + XGBoost — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Crypto Zipline Lab with 50 TradingView-style rule strategies and 3 walk-forward XGBoost strategies (standalone, ensemble, filter), supporting all lab timeframes.

**Architecture:** Modular signal files + `tv_catalog.py` as source of truth; `crypto_zipline_ml.py` builds Alpha158 + TV matrix features with walk-forward XGB; registry exposes 53 strategies to existing pandas/zipline runners and combo engine.

**Tech Stack:** Python 3.11+, pandas, qlib Alpha158, XGBModel (qlib.contrib), FastAPI, Vue 3 + Element Plus

**Spec:** [2026-06-08-crypto-tv-xgb-strategies-design.md](../specs/2026-06-08-crypto-tv-xgb-strategies-design.md)

---

## File map

| Action | Path | Role |
|--------|------|------|
| Create | `src/quant_rd_tool/crypto_zipline_strategies/tv_catalog.py` | 50 TV strategy metadata |
| Create | `src/quant_rd_tool/crypto_zipline_strategies/signals_trend.py` | 9 trend signals |
| Create | `src/quant_rd_tool/crypto_zipline_strategies/signals_momentum.py` | 10 momentum signals |
| Create | `src/quant_rd_tool/crypto_zipline_strategies/signals_volatility.py` | 3 volatility signals |
| Create | `src/quant_rd_tool/crypto_zipline_strategies/signals_volume.py` | 4 volume signals |
| Create | `src/quant_rd_tool/crypto_zipline_strategies/signals_combo.py` | 5 combo signals |
| Modify | `src/quant_rd_tool/crypto_zipline_strategies/signals.py` | Route new ids |
| Modify | `src/quant_rd_tool/crypto_zipline_strategies/__init__.py` | Registry from catalog |
| Create | `src/quant_rd_tool/crypto_zipline_ml_features.py` | Feature builder |
| Create | `src/quant_rd_tool/crypto_zipline_ml.py` | Walk-forward XGB + 3 runners |
| Modify | `src/quant_rd_tool/crypto_zipline_timeframes.py` | `ml_window_scale()` |
| Modify | `src/quant_rd_tool/crypto_zipline_strategies/zipline_algos.py` | ML target branch |
| Modify | `src/quant_rd_tool/routes/crypto.py` | Strategy list fields |
| Modify | `src/quant_trade_tool/src/api/crypto.ts` | TS types |
| Modify | `src/quant_trade_tool/src/views/CryptoZiplineLabView.vue` | Grouped select + ML params |
| Create | `tests/test_tv_catalog.py` | Catalog integrity |
| Create | `tests/test_tv_signals.py` | Signal unit tests |
| Create | `tests/test_crypto_zipline_ml.py` | Walk-forward leak tests |
| Create | `tests/test_crypto_zipline_ml_strategies.py` | ML backtest smoke |
| Modify | `tests/test_crypto_zipline_routes.py` | Count ≥ 53 |

---

### Task 1: TV catalog + timeframe scaling

**Files:**
- Create: `src/quant_rd_tool/crypto_zipline_strategies/tv_catalog.py`
- Modify: `src/quant_rd_tool/crypto_zipline_timeframes.py`
- Create: `tests/test_tv_catalog.py`

- [ ] **Step 1: Write failing test for catalog count**

```python
# tests/test_tv_catalog.py
from quant_rd_tool.crypto_zipline_strategies.tv_catalog import TV_STRATEGIES, list_tv_strategies

def test_tv_catalog_has_exactly_50():
    assert len(TV_STRATEGIES) == 50
    ids = [s["id"] for s in list_tv_strategies()]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/test_tv_catalog.py::test_tv_catalog_has_exactly_50 -v`

- [ ] **Step 3: Implement `tv_catalog.py`**

Define `TV_STRATEGIES: list[dict]` with all 50 ids (19 existing + 31 new from spec), each with:
`id, name, description, category, tv_ref, default_params, min_bars, signal_module`.

Export `list_tv_strategies()`, `get_tv_strategy(id)`.

- [ ] **Step 4: Add `ml_window_scale()` to timeframes**

```python
ML_WINDOW_SCALE = {"5m": 1.0, "15m": 1.0, "30m": 0.75, "1h": 0.25, "4h": 0.1, "1d": 0.05}

def ml_window_scale(timeframe: str) -> float:
    return ML_WINDOW_SCALE[normalize_timeframe(timeframe)]

def effective_ml_train_bars(timeframe: str, base: int = 2000) -> int:
    return max(200, int(base * ml_window_scale(timeframe)))
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `uv run pytest tests/test_tv_catalog.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/quant_rd_tool/crypto_zipline_strategies/tv_catalog.py \
  src/quant_rd_tool/crypto_zipline_timeframes.py tests/test_tv_catalog.py
git commit -m "feat(zipline): add TV strategy catalog with 50 entries and ML window scaling"
```

---

### Task 2: Trend + momentum signals (19 signals)

**Files:**
- Create: `src/quant_rd_tool/crypto_zipline_strategies/signals_trend.py`
- Create: `src/quant_rd_tool/crypto_zipline_strategies/signals_momentum.py`
- Modify: `src/quant_rd_tool/crypto_zipline_strategies/signals.py`
- Create: `tests/test_tv_signals.py` (partial)

- [ ] **Step 1: Write failing tests for 2 representative signals**

```python
# tests/test_tv_signals.py
from quant_rd_tool.crypto_zipline_strategies.signals import signal_for_strategy

def test_wavetrend_returns_none_during_warmup():
    closes = [100.0] * 20
    r = signal_for_strategy("wavetrend", closes, [0.0]*20, {"channel_len": 10, "avg_len": 21}, highs=closes, lows=closes)
    assert r is None

def test_hull_ma_trend_long_when_price_above_hull():
    # synthetic uptrend
    closes = [float(100 + i) for i in range(60)]
    r = signal_for_strategy("hull_ma_trend", closes, [1.0]*60, {"period": 55}, highs=closes, lows=closes)
    assert r == 1.0
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/test_tv_signals.py -v`

- [ ] **Step 3: Implement trend signals (9)**

`hull_ma_trend`, `dema_cross`, `t3_ma_trend`, `alma_trend`, `zero_lag_ema`, `ssl_channel`, `chandelier_exit`, `aroon_trend`, `linreg_channel`

Each returns `float | None` (0/1), follow existing `supertrend` patterns in `signals.py`.

- [ ] **Step 4: Implement momentum signals (10)**

`williams_r`, `cci_revert`, `tsi_momentum`, `ultimate_osc`, `wavetrend`, `fisher_transform`, `connors_rsi`, `rci_trend`, `coppock_curve`, `kst_momentum`

- [ ] **Step 5: Wire `signal_for_strategy()` + `SIGNAL_BY_STRATEGY`**

Import from submodules; add all 19 new ids.

- [ ] **Step 6: Run tests — expect PASS**

Run: `uv run pytest tests/test_tv_signals.py -v`

- [ ] **Step 7: Commit**

```bash
git commit -am "feat(zipline): add 19 TV trend and momentum signal functions"
```

---

### Task 3: Volatility + volume + combo signals (12 signals)

**Files:**
- Create: `signals_volatility.py`, `signals_volume.py`, `signals_combo.py`
- Modify: `signals.py`, `tests/test_tv_signals.py`

- [ ] **Step 1: Add parametrized test for all 31 new signal ids**

```python
NEW_IDS = [...]  # 31 ids from spec

@pytest.mark.parametrize("sid", NEW_IDS)
def test_new_signal_eventually_returns_target(sid):
    closes = [100 + (i % 7) - 3 for i in range(300)]
    ...
    # last call should not be None
```

- [ ] **Step 2: Implement remaining 12 signal modules**

Volatility (3): `squeeze_momentum`, `keltner_squeeze`, `atr_breakout`  
Volume (4): `mfi_revert`, `obv_trend`, `chaikin_mf`, `vwap_cross`  
Combo (5): `heikin_ashi_trend`, `elder_impulse`, `tdi_dynamic`, `ut_bot`, `range_filter`

- [ ] **Step 3: Run full signal tests**

Run: `uv run pytest tests/test_tv_signals.py -v`

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(zipline): complete 31 new TV signal implementations"
```

---

### Task 4: Registry integration (50 TV strategies)

**Files:**
- Modify: `crypto_zipline_strategies/__init__.py`
- Modify: `tests/test_tv_catalog.py`

- [ ] **Step 1: Test registry sync**

```python
def test_registry_has_all_tv_strategies():
    from quant_rd_tool.crypto_zipline_strategies import STRATEGY_REGISTRY
    from quant_rd_tool.crypto_zipline_strategies.tv_catalog import TV_STRATEGIES
    for spec in TV_STRATEGIES:
        assert spec["id"] in STRATEGY_REGISTRY
```

- [ ] **Step 2: Refactor registry build**

Loop `TV_STRATEGIES` to register runners via generic `_run_signal_strategy` lambda (pattern from `adx_trend`).

Keep existing custom runners (`ma_crossover`, etc.) or migrate all to signal-only where equivalent.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_tv_catalog.py tests/test_crypto_zipline_algos.py -v`

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(zipline): wire 50 TV strategies into STRATEGY_REGISTRY"
```

---

### Task 5: ML feature builder

**Files:**
- Create: `src/quant_rd_tool/crypto_zipline_ml_features.py`
- Create: `tests/test_crypto_zipline_ml.py`

- [ ] **Step 1: Write failing test — no future leak**

```python
def test_build_features_uses_only_past_bars():
    # df with known pattern; features at index t must not change when future rows appended
    ...
```

- [ ] **Step 2: Implement `build_tv_signal_matrix(df, strategy_ids) -> pd.DataFrame`**

Column per strategy id; row per bar; use incremental `signal_for_strategy` loop (reuse `_run_signal_strategy` logic).

- [ ] **Step 3: Implement `build_alpha158_features(df, timeframe) -> pd.DataFrame`**

Thin wrapper around qlib feature extraction adapted for in-memory OHLCV (reference `qlib_ml.py`); handle insufficient bars gracefully.

- [ ] **Step 4: Implement `build_ml_feature_frame(df, timeframe, include_tv=True)`**

Concat Alpha158 + TV matrix + optional rolling vote ratio.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_crypto_zipline_ml.py -v`

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(zipline): add ML feature builder with TV signal matrix"
```

---

### Task 6: Walk-forward XGB engine

**Files:**
- Create: `src/quant_rd_tool/crypto_zipline_ml.py`
- Modify: `tests/test_crypto_zipline_ml.py`

- [ ] **Step 1: Write failing test for walk-forward targets**

```python
def test_walk_forward_no_peek():
    targets = compute_walk_forward_targets(df, params, timeframe="15m")
    # changing last row of df must not change targets[:-2]
    ...
```

- [ ] **Step 2: Implement `compute_walk_forward_targets()`**

- Label: `sign(close[t+horizon]/close[t] - 1)`
- Train on `[t-train, t)` every `retrain_every` bars
- Use qlib `XGBModel` with minimal hyperparams (match `qlib_ml._fit_xgb`)
- Return `pd.Series` of 0/1 targets aligned to df index

- [ ] **Step 3: Implement runners**

```python
def run_xgb_alpha158(df, params, capital_base, timeframe) -> dict
def run_xgb_tv_ensemble(df, params, capital_base, timeframe) -> dict
def run_xgb_tv_filter(df, params, capital_base, timeframe) -> dict  # base_strategy param
```

Each attaches `ml_metrics` to result dict (IC, hit_rate, feature_importance top 5).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_crypto_zipline_ml.py -v`

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(zipline): walk-forward XGB strategies for crypto lab"
```

---

### Task 7: Registry + runner + zipline algo hook

**Files:**
- Modify: `crypto_zipline_strategies/__init__.py`
- Modify: `crypto_zipline_runner.py`
- Modify: `crypto_zipline_strategies/zipline_algos.py`
- Create: `tests/test_crypto_zipline_ml_strategies.py`

- [ ] **Step 1: Register 3 ML strategies in registry**

```python
"xgb_alpha158": {"source": "ml", "category": "ml", ...}
"xgb_tv_ensemble": {...}
"xgb_tv_filter": {"default_params": {"base_strategy": "supertrend", ...}}
```

- [ ] **Step 2: Branch in `run_pandas_backtest` / `get_runner`**

If strategy_id starts with `xgb_`, delegate to `crypto_zipline_ml` runners; pass `timeframe` from caller.

- [ ] **Step 3: Extend `zipline_algos._compute_target` for ML**

Precompute target series before zipline run (ML not feasible bar-by-bar inside zipline); inject via context for zipline path.

- [ ] **Step 4: End-to-end smoke test**

```python
def test_xgb_alpha158_pandas_backtest_smoke(synthetic_ohlcv_500):
    result = run_pandas_backtest(df, strategy_id="xgb_alpha158", ...)
    assert "metrics" in result
    assert result["metrics"]["trade_count"] >= 0
```

Run: `uv run pytest tests/test_crypto_zipline_ml_strategies.py -v`

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(zipline): integrate XGB strategies into backtest runners"
```

---

### Task 8: API + frontend

**Files:**
- Modify: `routes/crypto.py`
- Modify: `api/crypto.ts`
- Modify: `CryptoZiplineLabView.vue`
- Modify: `tests/test_crypto_zipline_routes.py`

- [ ] **Step 1: Extend `list_strategies()` response**

Include `category`, `source`, `tv_ref` from registry/catalog.

- [ ] **Step 2: Update TS interface `CryptoZiplineStrategy`**

- [ ] **Step 3: UI — grouped strategy select**

```vue
<el-option-group v-for="cat in strategyCategories" :label="cat.label">
  <el-option v-for="s in cat.items" ... />
</el-option-group>
```

Add `filterable` on select. When ML strategy selected, show extra form fields.

- [ ] **Step 4: Display ML metrics in result panel**

If `result.ml_metrics` present, show IC / hit rate / top features.

- [ ] **Step 5: Route test**

```python
def test_strategies_list_at_least_53(client):
    r = client.get("/api/v1/crypto/zipline/strategies")
    assert len(r.json()) >= 53
```

Run: `uv run pytest tests/test_crypto_zipline_routes.py -v`

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(zipline): grouped TV/ML strategy UI and API metadata"
```

---

### Task 9: Final verification

- [ ] **Run full test suite for zipline**

Run: `uv run pytest tests/test_tv_catalog.py tests/test_tv_signals.py tests/test_crypto_zipline_ml.py tests/test_crypto_zipline_ml_strategies.py tests/test_crypto_zipline_routes.py tests/test_crypto_zipline_algos.py tests/test_crypto_zipline_combo.py -v`

- [ ] **Manual smoke (optional)**

1. Open Crypto 策略实验室
2. Select `wavetrend` on 15m BTC — run backtest
3. Select `xgb_tv_ensemble` — verify ML metrics appear
4. Select `xgb_tv_filter` with base `supertrend`

- [ ] **Update spec approval checkbox + README one-liner**

- [ ] **Final commit**

```bash
git commit -am "docs: mark crypto TV+XGB strategies spec implemented"
```

---

## Execution handoff

Plan complete. Choose:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — implement all tasks in this session with checkpoints

Which approach?
