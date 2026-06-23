# A-Share VectorBT Lab (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an independent A-share single-stock backtest lab using AkShare data, VectorBT signals, full A-share execution rules, and QuantStats reports.

**Architecture:** VectorBT generates indicators/signals → `target` column → `run_ashare_bar_backtest` → QuantStats HTML + JSON metrics; artifacts under `data/stocks/vbt_lab/`. New API router + Vue page parallel to Stock Zipline Lab.

**Tech Stack:** Python 3.11+, FastAPI, VectorBT, QuantStats, AkShare (existing), Vue 3 + Element Plus

**Spec:** [docs/superpowers/specs/2026-06-22-astock-vbt-lab-design.md](../specs/2026-06-22-astock-vbt-lab-design.md)

---

## File map

| Action | Path | Role |
|--------|------|------|
| Create | `src/quant_rd_tool/stock_vbt_strategies.py` | 4 strategy templates + registry |
| Create | `src/quant_rd_tool/stock_vbt_reports.py` | QuantStats HTML + metrics JSON |
| Create | `src/quant_rd_tool/stock_vbt_lab.py` | Orchestration, persistence, data load |
| Create | `src/quant_rd_tool/routes/stocks_vbt.py` | REST API |
| Modify | `src/quant_rd_tool/routes/__init__.py` | Register router |
| Modify | `pyproject.toml` | Add vectorbt, quantstats |
| Create | `tests/test_stock_vbt_strategies.py` | Strategy unit tests |
| Create | `tests/test_stock_vbt_lab.py` | Lab + ashare integration |
| Create | `tests/test_stock_vbt_routes.py` | API tests |
| Create | `tests/fixtures/ashare_vbt_daily.csv` | Small OHLCV fixture |
| Create | `src/quant_trade_tool/src/api/stocks.ts` additions | `vbtApi` types + methods (or extend existing) |
| Create | `src/quant_trade_tool/src/views/StockVbtLabView.vue` | Main UI |
| Modify | `src/quant_trade_tool/src/router/index.ts` | Route `/stock-vbt` |
| Modify | `src/quant_trade_tool/src/layouts/MainLayout.vue` | Nav item |

---

### Task 1: Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1:** Add to `dependencies`:
  ```toml
  "vectorbt>=0.26.0",
  "quantstats>=0.0.62",
  ```
- [ ] **Step 2:** Run `uv sync`
- [ ] **Step 3:** Verify imports:
  ```bash
  uv run python -c "import vectorbt; import quantstats; print('ok')"
  ```

---

### Task 2: Strategy registry + signals

**Files:**
- Create: `src/quant_rd_tool/stock_vbt_strategies.py`
- Create: `tests/test_stock_vbt_strategies.py`
- Create: `tests/fixtures/ashare_vbt_daily.csv` (≥60 rows synthetic OHLCV)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_stock_vbt_strategies.py
import pandas as pd
from quant_rd_tool.stock_vbt_strategies import get_strategy, list_strategies, build_target_series

def _fixture_df():
    path = Path(__file__).parent / "fixtures" / "ashare_vbt_daily.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    return df.set_index("date")

def test_list_strategies_has_four():
    ids = {s["id"] for s in list_strategies()}
    assert ids == {"sma_cross", "rsi_revert", "macd_cross", "bb_breakout"}

@pytest.mark.parametrize("sid", ["sma_cross", "rsi_revert", "macd_cross", "bb_breakout"])
def test_build_target_binary(sid):
    df = _fixture_df()
    spec = get_strategy(sid)
    out = build_target_series(df, sid, spec["default_params"])
    assert "target" in out.columns
    assert set(out["target"].dropna().unique()).issubset({0, 1})
```

- [ ] **Step 2:** Run tests — expect FAIL

```bash
uv run pytest tests/test_stock_vbt_strategies.py -v
```

- [ ] **Step 3: Implement `stock_vbt_strategies.py`**

Key functions:
- `list_strategies() -> list[dict]`
- `get_strategy(strategy_id: str) -> dict`
- `build_target_series(df, strategy_id, params) -> pd.DataFrame` (adds `target`)

Use VectorBT indicators:
- `vbt.MA.run` for SMA cross
- `vbt.RSI.run` for RSI
- `vbt.MACD.run` for MACD
- `vbt.BBANDS.run` for Bollinger

Convert entries/exits to `target` via forward-fill: 1 after entry until exit.

- [ ] **Step 4:** Run tests — expect PASS

- [ ] **Step 5: Commit**
  ```bash
  git add pyproject.toml uv.lock src/quant_rd_tool/stock_vbt_strategies.py tests/
  git commit -m "feat(astock-vbt): add VectorBT strategy registry with four templates"
  ```

---

### Task 3: QuantStats report builder

**Files:**
- Create: `src/quant_rd_tool/stock_vbt_reports.py`
- Test in: `tests/test_stock_vbt_lab.py` (later) or small `tests/test_stock_vbt_reports.py`

- [ ] **Step 1: Write failing test**

```python
def test_build_quantstats_artifacts(tmp_path):
    import pandas as pd
    from quant_rd_tool.stock_vbt_reports import build_report_artifacts
    idx = pd.date_range("2020-01-01", periods=100, freq="B")
    returns = pd.Series(0.001, index=idx)
    out = build_report_artifacts(returns, tmp_path)
    assert (tmp_path / "metrics.json").exists()
    assert (tmp_path / "quantstats.html").exists()
    assert "sharpe" in json.loads((tmp_path / "metrics.json").read_text())
```

- [ ] **Step 2:** Run — FAIL

- [ ] **Step 3: Implement `build_report_artifacts(returns: pd.Series, out_dir: Path) -> dict`**
  - Use `quantstats.reports.html(returns, output=...)`
  - Extract key metrics via `quantstats.stats` into `metrics.json`

- [ ] **Step 4:** PASS + commit

---

### Task 4: Lab orchestration

**Files:**
- Create: `src/quant_rd_tool/stock_vbt_lab.py`
- Create: `tests/test_stock_vbt_lab.py`

- [ ] **Step 1: Write failing integration test**

```python
def test_run_vbt_backtest_on_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr("quant_rd_tool.stock_vbt_lab.VBT_LAB_DIR", tmp_path)
    # monkeypatch load_ohlcv to return fixture df
    result = run_backtest(
        symbol="600519",
        start="2020-01-01",
        end="2020-06-01",
        strategy_id="sma_cross",
        strategy_params={"fast": 5, "slow": 20},
        capital_base=100_000,
    )
    assert result["run_id"]
    assert "metrics" in result
    assert (tmp_path / result["run_id"] / "params.json").exists()
```

- [ ] **Step 2:** FAIL

- [ ] **Step 3: Implement `stock_vbt_lab.py`**

```python
VBT_LAB_DIR = Path("data/stocks/vbt_lab")

def load_ohlcv(symbol, start, end, *, data_dir="data/stocks", refresh=False) -> pd.DataFrame:
    # Use stock_storage paths + market_data.fetch_stock_daily on refresh

def run_backtest(...) -> dict:
    df = load_ohlcv(...)
    work = build_target_series(df, strategy_id, params)
    with ashare_backtest_context(symbol=symbol, use_ashare=True):
        bt = run_ashare_bar_backtest(work, capital_base=..., warmup=min_bars, target_col="target", symbol=symbol)
  # build returns series from equity_curve
  # build_report_artifacts(...)
  # append runs.jsonl, save params/trades/equity
  return {run_id, metrics, execution_stats, ...}

def list_runs(limit=20, symbol=None) -> list[dict]
def get_run(run_id) -> dict
```

- [ ] **Step 4:** Add T+1 test using synthetic signals (buy today, sell same day — position should not drop same bar)

- [ ] **Step 5:** PASS + commit

---

### Task 5: API routes

**Files:**
- Create: `src/quant_rd_tool/routes/stocks_vbt.py`
- Modify: `src/quant_rd_tool/routes/__init__.py`
- Create: `tests/test_stock_vbt_routes.py`

- [ ] **Step 1: Write route tests with monkeypatch**

```python
def test_vbt_strategies_route():
    r = client.get("/api/v1/stocks/vbt/strategies")
    assert r.status_code == 200
    assert len(r.json()) == 4

def test_vbt_backtest_route(monkeypatch):
    monkeypatch.setattr("quant_rd_tool.stock_vbt_lab.run_backtest", lambda **kw: {...})
    r = client.post("/api/v1/stocks/vbt/backtest", json={...})
    assert r.status_code == 200
```

- [ ] **Step 2:** Implement Pydantic models + endpoints per spec

- [ ] **Step 3:** Register:
  ```python
  from quant_rd_tool.routes import stocks_vbt
  api_router.include_router(stocks_vbt.router, prefix="/stocks/vbt", tags=["stocks-vbt"])
  ```

- [ ] **Step 4:** PASS + commit

---

### Task 6: Optional async job (YAGNI defer if sync is fast enough)

**Files:**
- Modify: `src/quant_rd_tool/routes/jobs.py`
- Modify: `src/quant_rd_tool/job_runner.py`

- [ ] **Step 1:** Add `vbt_backtest` job type + handler calling `run_backtest`
- [ ] **Step 2:** `POST /api/v1/jobs/vbt-backtest` — skip if Phase 1 sync path is sufficient; document in plan as optional stretch

---

### Task 7: Frontend API client

**Files:**
- Modify: `src/quant_trade_tool/src/api/stocks.ts` (or create `stocksVbt.ts`)

- [ ] **Step 1:** Add types: `VbtStrategy`, `VbtBacktestRequest`, `VbtBacktestResult`, `VbtRunSummary`
- [ ] **Step 2:** Add methods:
  ```ts
  vbtStrategies: () => http.get<VbtStrategy[]>("/stocks/vbt/strategies"),
  vbtBacktest: (body) => http.post<VbtBacktestResult>("/stocks/vbt/backtest", body),
  vbtRuns: (params?) => http.get("/stocks/vbt/runs", { params }),
  vbtRunReportUrl: (id) => `/api/v1/stocks/vbt/runs/${id}/report`,
  ```

---

### Task 8: Frontend page

**Files:**
- Create: `src/quant_trade_tool/src/views/StockVbtLabView.vue`
- Modify: `src/quant_trade_tool/src/router/index.ts`
- Modify: `src/quant_trade_tool/src/layouts/MainLayout.vue`

- [ ] **Step 1:** Form — symbol input, date range, strategy `<el-select>`, dynamic params from schema
- [ ] **Step 2:** On mount load strategies; on submit call `vbtBacktest`
- [ ] **Step 3:** Display metrics cards (total return, CAGR, Sharpe, max DD, win rate)
- [ ] **Step 4:** Reuse `EquityCurveChart` with equity JSON
- [ ] **Step 5:** Trades table + link to QuantStats report (`window.open(reportUrl)`)
- [ ] **Step 6:** Recent runs sidebar/table
- [ ] **Step 7:** `npm run build` passes

---

### Task 9: Verification

- [ ] **Step 1:**
  ```bash
  uv run pytest tests/test_stock_vbt_strategies.py tests/test_stock_vbt_lab.py tests/test_stock_vbt_routes.py -v
  ```
- [ ] **Step 2:**
  ```bash
  cd src/quant_trade_tool && npm run build
  ```
- [ ] **Step 3:** Manual smoke — `uv run quant-rd serve`, open `/stock-vbt`, backtest `600519` + `sma_cross`

---

## Notes for implementer

- **Do not modify** `StockZiplineLabView` or zipline engines.
- Reuse `stock_zipline_bundle.load_ohlcv_window` or `stock_storage` + `market_data` — pick one path, don't duplicate fetch logic twice.
- QuantStats needs `%` daily returns series indexed by date; align index with equity curve diff.
- `run_id` must be UUID; validate on report path to prevent traversal.
- If `vectorbt` install is heavy on macOS, document in README optional group — but default include per spec.

---

## Out of scope (do not implement in Phase 1)

- Optuna, LightGBM/XGBoost, PyPortfolioOpt, APScheduler
- Multi-symbol batch ranking
- Minute bars
