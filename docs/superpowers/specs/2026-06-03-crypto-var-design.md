# Crypto VaR (Value at Risk) — Design Spec

**Approved:** 2026-06-03  
**Scope:** Binance USDT-M perpetual + spot OHLCV (via ccxt)  
**Delivery:** API + Vue console page + light embeds in AnalyzeView / CryptoOpsView

## Goals

Provide crypto risk analytics using **historical simulation** with **VaR** and **CVaR (Expected Shortfall)**:

1. **Single-symbol VaR** — estimate 1-day (configurable) loss for a notional exposure from historical returns.
2. **Portfolio VaR** — read live perpetual positions, align multi-symbol returns, compute portfolio VaR/CVaR.
3. **Dedicated UI** at `/crypto-var` plus summary cards on existing crypto pages.

## v2.1 Monte Carlo (2026-06-03)

- `compute_monte_carlo_var`: 10k paths (configurable), GBM (normal) + Student-t (df from kurtosis).
- Exposed in `metrics[*].monte_carlo` with `gbm` / `student_t` legs and USDT amounts.
- API: `mc_n_sims`, `mc_seed` on symbol/portfolio endpoints.

## v2 enhancements (2026-06-03)

- Parametric VaR alongside historical (method spread).
- VaR backtest (violation rate vs expected).
- Return distribution stats + histogram bins.
- Fixed stress shocks (-3% / -5% / -10% / -20%).
- Portfolio: correlation matrix, marginal VaR contribution, var % of equity.
- Chinese narrative headline + bullets.
- UI: distribution bars, rolling VaR chart with breach markers.

## Non-goals (MVP)

- Monte Carlo simulation.
- Custom hypothetical weights (portfolio uses live positions only).
- Cross-exchange abstraction beyond Binance.
- Options Greeks or vol-surface risk.
- Scheduled VaR breach alerts (future: schedule_alert integration).

## User decisions (locked)

| Dimension | Choice |
|-----------|--------|
| Scope | Single-symbol + portfolio VaR |
| Method | Historical simulation + CVaR |
| UI | Standalone page + light embed in AnalyzeView & CryptoOpsView |
| Parameters | Fully configurable API; defaults: confidence `[0.95, 0.99]`, horizon 1 day, lookback 252 bars, timeframe `1d` |

## Architecture

### Backend module

New file: `src/quant_rd_tool/crypto_var.py`

| Function | Responsibility |
|----------|----------------|
| `compute_historical_var(returns, confidence, horizon_days)` | VaR from empirical return quantile |
| `compute_cvar(returns, confidence, horizon_days)` | Expected shortfall beyond VaR threshold |
| `build_symbol_var_report(...)` | Fetch OHLCV → returns → VaR/CVaR for one symbol |
| `build_portfolio_var_report(...)` | Fetch positions + multi-symbol OHLCV → portfolio VaR |
| `fetch_ohlcv_returns(symbols, timeframe, limit)` | Reuse `ccxt_data` patterns |
| `fetch_open_positions(ex, ...)` | ccxt `fetch_positions`; normalize like `perp_order_manager` |

### Calculation (historical simulation)

1. Daily log or simple returns from aligned close prices.
2. Horizon scaling: `r_scaled = r * sqrt(horizon_days)` (1-day: no scale).
3. **VaR(α)** = `-quantile(r_scaled, 1-α)`; express as USDT loss = `notional * var_pct`.
4. **CVaR(α)** = mean of returns ≤ `-VaR_pct` (tail average).
5. **Portfolio:** signed weights `w_i = signed_notional_i / sum(abs(notional))`; `r_port_t = Σ w_i * r_i,t`; apply steps 2–4 on `r_port` scaled by total gross exposure.

### API endpoints

Registered in `src/quant_rd_tool/routes/crypto.py`:

| Method | Path | Auth |
|--------|------|------|
| `GET` | `/api/v1/crypto/var/symbol` | No |
| `GET` | `/api/v1/crypto/var/portfolio` | Binance API key (read-only) |
| `GET` | `/api/v1/crypto/var/symbol/history` | No (rolling VaR series for charts) |

**Shared query params:** `timeframe`, `lookback_bars`, `horizon_days`, `confidence` (comma-separated, e.g. `0.95,0.99`), `notional_usdt` (symbol endpoint; default from latest price × 1 unit or user input).

**Portfolio extras:** `testnet`; auto-detect symbols from open positions.

**Error / empty states:**

- Missing API key → `{ "enabled": false, "error": "missing api key/secret" }`
- Insufficient history (< 30 bars) → `{ "error": "insufficient data", "observations": N }`
- No open positions → `{ "enabled": true, "positions": [], "metrics": null, "message": "no open positions" }`

**Symbol response shape:**

```json
{
  "symbol": "BTC",
  "method": "historical_simulation",
  "params": { "lookback_bars": 252, "horizon_days": 1, "confidence_levels": [0.95, 0.99], "timeframe": "1d" },
  "notional_usdt": 10000,
  "latest_price": 95000.0,
  "observations": 251,
  "metrics": {
    "0.95": { "var_usdt": 450.2, "var_pct": 0.045, "cvar_usdt": 620.1, "cvar_pct": 0.062 },
    "0.99": { "var_usdt": 780.5, "var_pct": 0.078, "cvar_usdt": 950.3, "cvar_pct": 0.095 }
  }
}
```

**Portfolio response adds:** `positions[]` (symbol, side, notional_usdt, weight), `gross_exposure_usdt`, `net_exposure_usdt`, `account_equity_usdt` (if available from balance), `diversification_ratio` (sum of individual VaRs / portfolio VaR).

### Frontend

| File | Change |
|------|--------|
| `CryptoVarView.vue` | New page: Tab「单标的」+ Tab「组合」; param form; VaR/CVaR stat cards; optional rolling VaR chart |
| `router/index.ts` | Route `/crypto-var`, name `crypto-var` |
| `MainLayout.vue` | Nav item「风险 VaR」under Crypto group |
| `api/crypto.ts` | `varSymbol()`, `varPortfolio()`, `varSymbolHistory()` + TypeScript interfaces |
| `AnalyzeView.vue` | Summary card: 1d 99% VaR; link to `/crypto-var?symbol=…` |
| `CryptoOpsView.vue` | Summary card: portfolio 1d 99% VaR; link to `/crypto-var?tab=portfolio` |

UI defaults match API defaults. Display VaR as positive USDT loss with percentage of notional/equity.

## Testing

`tests/test_crypto_var.py`:

- Known return series → VaR/CVaR match hand-computed quantiles.
- Portfolio with long + short → signed weights and portfolio returns correct.
- `< 30` observations → error payload.
- Empty positions → graceful empty state.
- Portfolio without API keys → `enabled: false`.

## File checklist

| Path | Action |
|------|--------|
| `src/quant_rd_tool/crypto_var.py` | Create |
| `src/quant_rd_tool/routes/crypto.py` | Add endpoints |
| `tests/test_crypto_var.py` | Create |
| `src/quant_trade_tool/src/api/crypto.ts` | Types + client |
| `src/quant_trade_tool/src/views/CryptoVarView.vue` | Create |
| `src/quant_trade_tool/src/router/index.ts` | Route |
| `src/quant_trade_tool/src/layouts/MainLayout.vue` | Nav |
| `AnalyzeView.vue` | Embed card |
| `CryptoOpsView.vue` | Embed card |
