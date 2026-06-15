# A-Share Transaction Model Design

**Status:** Approved 2026-06-15  
**Goal:** Institutional-grade A-share execution rules for portfolio Top-K and Zipline pandas backtests.

## Scope

- T+1 settlement, 100-share lots, stamp duty (sell-only), commission with minimum, optional transfer fee (SH)
- Limit up/down approximation via prior close ± board limit %
- Default `use_ashare_rules=True`; legacy crypto-style costs via `use_ashare_rules=False`
- Zipline subprocess auto-falls back to pandas when A-share rules enabled

## Modules

- `stock_ashare_execution.py` — fee schedule, board rules, limit checks, Top-K simulator
- `stock_ashare_pandas.py` — single-symbol bar backtest + context var for strategy runners

## Out of scope (v1)

- Walk-forward OOS, audit chain, ST/停牌 flags, ChiNext 200-share lots
