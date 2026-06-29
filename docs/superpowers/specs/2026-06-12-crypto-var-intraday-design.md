# Crypto VaR v3 — Intraday & Rolling Breach

**Approved:** 2026-06-12  
**Scope:** Extend existing `crypto_var.py` (Option C)

## Goals

1. **Intraday timeframes** — `1d` / `4h` / `1h` with bar-based holding period (`horizon_bars`).
2. **Rolling VaR history** — configurable window per timeframe (e.g. 168 × 1h bars).
3. **Rolling breach detection** — compare latest bar return vs current VaR; expose API + scheduler alerts.

## Calculation

- `bars_per_day`: 1d→1, 4h→6, 1h→24
- Effective horizon (days) = `horizon_bars / bars_per_day` when `horizon_bars > 0`, else `horizon_days`
- Scale returns: `r × sqrt(effective_horizon_days)` (unchanged formula)
- Default lookback: 1d→252, 4h→360, 1h→720

## API

| Method | Path | New params |
|--------|------|------------|
| GET | `/crypto/var/symbol` | `horizon_bars` |
| GET | `/crypto/var/portfolio` | `horizon_bars`, `timeframe` (fix portfolio alert pass-through) |
| GET | `/crypto/var/symbol/history` | `horizon_bars`, timeframe-aware defaults |
| GET | `/crypto/var/symbol/breach` | **new** — rolling breach for one symbol |
| GET | `/crypto/var/portfolio/breach` | **new** — rolling breach for live portfolio |

## Scheduler

Extend `schedule_alerts.var`:

- `timeframe`, `horizon_bars`, `on_rolling_var_breach`
- Cycle fields: `var_timeframe`, `var_breach`, `var_actual_return`, `var_horizon_bars`
- Alert rule: `var_rolling_breach` when latest bar return < -VaR

## UI

- `CryptoVarView`: timeframe selector, horizon bars, breach banner, dynamic rolling chart label
- `SchedulesView`: document new var config keys

## Tests

- `resolve_horizon_days` / `bars_per_day`
- Intraday VaR scaling
- `build_symbol_var_breach` breached vs not
- `evaluate_var_breaches` rolling breach
