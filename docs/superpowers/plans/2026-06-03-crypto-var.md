# Crypto VaR Module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add historical-simulation VaR + CVaR for single crypto symbols and live perpetual portfolios, exposed via REST API and a new `CryptoVarView` page with summary embeds.

**Architecture:** Single backend module `crypto_var.py` owns pure math + OHLCV/position fetching (ccxt patterns from `ccxt_data` / `perp_account_analytics`). Three GET routes under `/crypto/var/*`. Frontend follows `CryptoOptionsVolView` conventions.

**Tech Stack:** Python 3.11+, pandas, numpy, FastAPI, pytest; Vue 3 + Element Plus + axios.

**Spec:** `docs/superpowers/specs/2026-06-03-crypto-var-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| `src/quant_rd_tool/crypto_var.py` | VaR/CVaR math, symbol & portfolio reports, data fetch |
| `tests/test_crypto_var.py` | Unit tests (no live exchange) |
| `src/quant_rd_tool/routes/crypto.py` | Three GET endpoints |
| `src/quant_trade_tool/src/api/crypto.ts` | TS types + `cryptoApi.var*` |
| `src/quant_trade_tool/src/views/CryptoVarView.vue` | Full UI (tabs, params, chart) |
| `src/quant_trade_tool/src/router/index.ts` | Route `/crypto-var` |
| `src/quant_trade_tool/src/layouts/MainLayout.vue` | Nav link |
| `src/quant_trade_tool/src/views/AnalyzeView.vue` | VaR summary card |
| `src/quant_trade_tool/src/views/CryptoOpsView.vue` | Portfolio VaR summary card |

---

### Task 1: Core VaR/CVaR math (TDD)

**Files:**
- Create: `src/quant_rd_tool/crypto_var.py`
- Create: `tests/test_crypto_var.py`

- [ ] **Step 1: Write failing tests for pure functions**

```python
# tests/test_crypto_var.py
import numpy as np
import pandas as pd
import pytest

from quant_rd_tool.crypto_var import (
    compute_cvar,
    compute_historical_var,
    returns_from_close,
)


def test_returns_from_close_simple():
    s = pd.Series([100.0, 110.0, 99.0])
    r = returns_from_close(s)
    assert len(r.dropna()) == 2
    assert r.iloc[-1] == pytest.approx(99.0 / 110.0 - 1)


def test_historical_var_known_series():
    # 100 obs: losses at bottom 5% ~ -0.05
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0, 0.02, 200))
    var_pct = compute_historical_var(rets, confidence=0.95, horizon_days=1)
    assert var_pct > 0  # expressed as positive loss fraction


def test_cvar_exceeds_var():
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.standard_t(5, size=500) * 0.02)
    var_pct = compute_historical_var(rets, confidence=0.95, horizon_days=1)
    cvar_pct = compute_cvar(rets, confidence=0.95, horizon_days=1)
    assert cvar_pct >= var_pct


def test_insufficient_data_raises():
    rets = pd.Series([0.01, -0.02])
    with pytest.raises(ValueError, match="insufficient"):
        compute_historical_var(rets, confidence=0.95, horizon_days=1)
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /Users/worldunion/projects/pythonprojects/claudedemo/quant_rd_tool
uv run pytest tests/test_crypto_var.py -v
```

Expected: `ModuleNotFoundError` or import error.

- [ ] **Step 3: Implement minimal math**

```python
# src/quant_rd_tool/crypto_var.py (core excerpt)
MIN_OBSERVATIONS = 30

def returns_from_close(close: pd.Series) -> pd.Series:
    return close.astype(float).pct_change().dropna()

def _scale_returns(returns: pd.Series, horizon_days: int) -> pd.Series:
    if horizon_days <= 1:
        return returns
    return returns * (horizon_days ** 0.5)

def compute_historical_var(returns: pd.Series, *, confidence: float, horizon_days: int = 1) -> float:
    r = _scale_returns(returns.dropna(), horizon_days)
    if len(r) < MIN_OBSERVATIONS:
        raise ValueError(f"insufficient data: need >={MIN_OBSERVATIONS}, got {len(r)}")
    q = float(r.quantile(1 - confidence))
    return round(max(-q, 0.0), 8)

def compute_cvar(returns: pd.Series, *, confidence: float, horizon_days: int = 1) -> float:
    r = _scale_returns(returns.dropna(), horizon_days)
    if len(r) < MIN_OBSERVATIONS:
        raise ValueError(f"insufficient data: need >={MIN_OBSERVATIONS}, got {len(r)}")
    var_pct = compute_historical_var(returns, confidence=confidence, horizon_days=horizon_days)
    tail = r[r <= -var_pct]
    if tail.empty:
        tail = r[r <= r.quantile(1 - confidence)]
    cvar = -float(tail.mean()) if len(tail) else var_pct
    return round(max(cvar, var_pct), 8)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_crypto_var.py -v
```

---

### Task 2: Symbol VaR report builder

**Files:**
- Modify: `src/quant_rd_tool/crypto_var.py`
- Modify: `tests/test_crypto_var.py`

- [ ] **Step 1: Write failing test with mocked OHLCV**

```python
def test_build_symbol_var_report(monkeypatch):
    from quant_rd_tool import crypto_var as cv

    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    close = pd.Series(100 * (1 + np.random.default_rng(1).normal(0, 0.01, 100)).cumprod(), index=dates)
    df = pd.DataFrame({"date": dates, "close": close, "symbol": "BTC"})

    monkeypatch.setattr(cv, "fetch_ohlcv_df", lambda **kw: df)

    report = cv.build_symbol_var_report(
        symbol="BTC",
        notional_usdt=10_000,
        lookback_bars=90,
        confidence_levels=[0.95, 0.99],
        horizon_days=1,
        timeframe="1d",
    )
    assert report["symbol"] == "BTC"
    assert "0.95" in report["metrics"]
    assert report["metrics"]["0.95"]["var_usdt"] > 0
```

- [ ] **Step 2: Implement `fetch_ohlcv_df` + `build_symbol_var_report`**

Use `ccxt_data.fetch_ohlcv` (or existing helper) for live fetch; accept injected df in tests via module-level fetch function.

```python
def build_symbol_var_report(
    symbol: str,
    *,
    notional_usdt: float,
    lookback_bars: int = 252,
    confidence_levels: list[float] | None = None,
    horizon_days: int = 1,
    timeframe: str = "1d",
) -> dict[str, Any]:
    confidence_levels = confidence_levels or [0.95, 0.99]
    df = fetch_ohlcv_df(symbol=symbol, timeframe=timeframe, limit=lookback_bars + 1)
    close = df.set_index("date")["close"] if "date" in df.columns else df["close"]
    rets = returns_from_close(close)
    latest_price = float(close.iloc[-1])
    metrics = {}
    for c in confidence_levels:
        key = f"{c:.2f}".rstrip("0").rstrip(".") if c != int(c) else str(int(c))
        # normalize key like "0.95"
        key = f"{c:.2f}"
        var_pct = compute_historical_var(rets, confidence=c, horizon_days=horizon_days)
        cvar_pct = compute_cvar(rets, confidence=c, horizon_days=horizon_days)
        metrics[key] = {
            "var_pct": var_pct,
            "cvar_pct": cvar_pct,
            "var_usdt": round(notional_usdt * var_pct, 4),
            "cvar_usdt": round(notional_usdt * cvar_pct, 4),
        }
    return {
        "symbol": symbol.upper(),
        "method": "historical_simulation",
        "params": {...},
        "notional_usdt": notional_usdt,
        "latest_price": latest_price,
        "observations": int(len(rets)),
        "metrics": metrics,
    }
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_crypto_var.py::test_build_symbol_var_report -v
```

---

### Task 3: Portfolio VaR + rolling history

**Files:**
- Modify: `src/quant_rd_tool/crypto_var.py`
- Modify: `tests/test_crypto_var.py`

- [ ] **Step 1: Tests for portfolio aggregation**

```python
def test_portfolio_returns_long_short():
    from quant_rd_tool.crypto_var import build_portfolio_returns

    weights = {"BTC": 0.6, "ETH": -0.4}  # signed
    rets_map = {
        "BTC": pd.Series([0.01, -0.02, 0.03]),
        "ETH": pd.Series([0.02, -0.01, 0.01]),
    }
    port = build_portfolio_returns(weights, rets_map)
    assert len(port) == 3
    assert port.iloc[0] == pytest.approx(0.6 * 0.01 + (-0.4) * 0.02)


def test_build_portfolio_var_report_empty_positions():
    from quant_rd_tool import crypto_var as cv
    report = cv.build_portfolio_var_report(positions=[], ...)
    assert report["positions"] == []
    assert report.get("metrics") is None
```

- [ ] **Step 2: Implement `fetch_all_open_positions`, `build_portfolio_var_report`, `build_symbol_var_history`**

- Fetch all non-flat positions via `ex.fetch_positions()` (pattern from `perp_order_manager.get_position`).
- Normalize: base symbol, side, signed `notional_usdt` (from `notional` or `contracts * markPrice`).
- Align return DataFrames on date index (inner join).
- Weights: `signed_notional / sum(abs(notional))`.
- `diversification_ratio` = `sum(individual_var_usdt) / portfolio_var_usdt` (if portfolio_var > 0).

- [ ] **Step 3: Run full test file**

```bash
uv run pytest tests/test_crypto_var.py -q
```

---

### Task 4: API routes

**Files:**
- Modify: `src/quant_rd_tool/routes/crypto.py` (append before options routes ~line 742)

- [ ] **Step 1: Add endpoints**

```python
@router.get("/var/symbol")
def crypto_var_symbol(
    symbol: str = "BTC",
    notional_usdt: float = 0.0,
    timeframe: str = "1d",
    lookback_bars: int = 252,
    horizon_days: int = 1,
    confidence: str = "0.95,0.99",
) -> dict[str, Any]:
    from quant_rd_tool.crypto_var import build_symbol_var_report, parse_confidence_levels

    levels = parse_confidence_levels(confidence)
    try:
        return build_symbol_var_report(
            symbol=symbol,
            notional_usdt=notional_usdt,  # 0 => default 1 unit * latest price inside builder
            timeframe=timeframe,
            lookback_bars=min(lookback_bars, 2000),
            horizon_days=horizon_days,
            confidence_levels=levels,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/var/portfolio")
def crypto_var_portfolio(
    testnet: bool = False,
    timeframe: str = "1d",
    lookback_bars: int = 252,
    horizon_days: int = 1,
    confidence: str = "0.95,0.99",
) -> dict[str, Any]:
    ...


@router.get("/var/symbol/history")
def crypto_var_symbol_history(
    symbol: str = "BTC",
    window: int = 60,
    confidence: float = 0.99,
    ...
) -> dict[str, Any]:
    ...
```

- [ ] **Step 2: Smoke test via pytest or curl**

```bash
uv run pytest tests/test_crypto_var.py -q
# optional manual:
uv run quant-rd serve &
curl -s "http://127.0.0.1:8000/api/v1/crypto/var/symbol?symbol=BTC&notional_usdt=10000" | head
```

---

### Task 5: Frontend API + CryptoVarView

**Files:**
- Modify: `src/quant_trade_tool/src/api/crypto.ts`
- Create: `src/quant_trade_tool/src/views/CryptoVarView.vue`
- Modify: `src/quant_trade_tool/src/router/index.ts`
- Modify: `src/quant_trade_tool/src/layouts/MainLayout.vue`

- [ ] **Step 1: Add TS interfaces + methods**

```typescript
export interface VarMetric {
  var_usdt: number;
  var_pct: number;
  cvar_usdt: number;
  cvar_pct: number;
}

export interface SymbolVarReport {
  symbol: string;
  method: string;
  notional_usdt: number;
  latest_price: number;
  observations: number;
  metrics: Record<string, VarMetric>;
}

// cryptoApi:
varSymbol: (params: {...}) => http.get("/crypto/var/symbol", { params }),
varPortfolio: (params: {...}) => http.get("/crypto/var/portfolio", { params }),
varSymbolHistory: (params: {...}) => http.get("/crypto/var/symbol/history", { params }),
```

- [ ] **Step 2: Create `CryptoVarView.vue`**

Follow `CryptoOptionsVolView.vue` layout:
- Page title「风险 VaR」
- `el-tabs`: `symbol` | `portfolio`
- Form: symbol select, notional, lookback, horizon, confidence checkboxes
- Stat cards for 95%/99% VaR & CVaR (USDT + %)
- Portfolio tab: load button, positions table, metrics
- Optional: simple line chart for rolling VaR from history endpoint (use existing chart lib if project has one; else el-table of dates)

- [ ] **Step 3: Register route + nav**

```typescript
// router/index.ts
{ path: "crypto-var", name: "crypto-var", component: () => import("@/views/CryptoVarView.vue") },
```

```typescript
// MainLayout.vue crypto group
{ path: "/crypto-var", icon: "Warning", label: "风险 VaR" },
```

- [ ] **Step 4: Manual UI check**

```bash
cd src/quant_trade_tool && npm run dev
# Open /crypto-var, run symbol VaR for BTC
```

---

### Task 6: Embed summary cards

**Files:**
- Modify: `src/quant_trade_tool/src/views/AnalyzeView.vue`
- Modify: `src/quant_trade_tool/src/views/CryptoOpsView.vue`

- [ ] **Step 1: AnalyzeView — after analysis completes, fetch VaR**

On `onDone`, call `cryptoApi.varSymbol({ symbol: form.symbol, notional_usdt: 10000, confidence: "0.99" })` (lazy, non-blocking). Show card:

> 1 日 99% VaR：{var_usdt} USDT ({var_pct}%)
> [查看详情 →](/crypto-var?symbol=BTC)

- [ ] **Step 2: CryptoOpsView — on mount or refresh balances, fetch portfolio VaR**

If `balances.enabled`, call `varPortfolio`. Show card with 99% VaR vs account equity.

- [ ] **Step 3: Verify links with query params**

`/crypto-var?symbol=ETH&tab=symbol`
`/crypto-var?tab=portfolio`

---

### Task 7: Final verification

- [ ] **Run all crypto-related tests**

```bash
uv run pytest tests/test_crypto_var.py tests/test_perp_account_analytics.py -q
```

- [ ] **Update README** (one line under Crypto API section)

```
GET /api/v1/crypto/var/symbol — historical VaR/CVaR for a symbol
GET /api/v1/crypto/var/portfolio — portfolio VaR from live perp positions
```

---

## Verify checklist

```bash
uv run pytest tests/test_crypto_var.py -q
uv run quant-rd serve --reload
cd src/quant_trade_tool && npm run dev
```

1. `/crypto-var` → BTC 单标的 VaR 显示 95%/99%
2. `/crypto-var?tab=portfolio` → 有 API Key 时显示持仓组合 VaR
3. `/analyze` → 分析结果下方 VaR 摘要卡片
4. `/crypto-ops` → 账户区组合 VaR 摘要
