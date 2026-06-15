# Walk-Forward / OOS Protocol Design

**Status:** Approved 2026-06-15 (Milestone B)  
**Goal:** Unified out-of-sample validation reporting for qlib fixed-split ML and zipline walk-forward ML.

## Protocol types

1. **fixed_split** — qlib Alpha158 train/valid/test (60/20/20); OOS = valid + test
2. **walk_forward** — expanding window retrain; OOS = all bars after initial train window

## Gate defaults

- test IC ≥ 0.02
- direction accuracy ≥ 52%
- test samples ≥ 20

## Modules

- `oos_protocol.py` — segments, reports, gates, markdown
- `qlib_ml.py` — attach `oos_protocol` to ML results
- `crypto_zipline_ml.py` — aggregate OOS metrics + protocol on walk-forward
- UI — BacktestView, StockZiplineLabView OOS panel
