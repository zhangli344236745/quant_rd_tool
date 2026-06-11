# Crypto Workflow — Design Spec

**Approved:** 2026-06-10  
**Scope:** Configurable ordered pipeline (DAG-lite) combining technical, qlib ML, zipline strategy, VaR, options vol → investment advice

## User decisions

| Dimension | Choice |
|-----------|--------|
| Shape | Configurable ordered steps (DAG-lite) |
| Scope | Single-symbol templates |
| Steps v1 | technical, qlib_ml, zipline_strategy, var_symbol, options_vol, advice_synth |
| Delivery | `/crypto-workflow` page + REST API |

## Architecture

- `crypto_workflow.py` — step registry, executor, advice synthesis
- `crypto_workflow_storage.py` — templates + run history under `data/crypto/workflows/`
- Routes under `/api/v1/crypto/workflow/*`

## Advice synthesis

- Direction score from technical + ML + strategy target_pct
- VaR gate: 99% VaR / notional > 8% → downgrade stance, cap `suggested_position_pct`
- Options context adds hedge/vol bullets
- Output: stance, action, confidence, suggested_position_pct, risk_level, headline, bullets, markdown

## Non-goals (v1)

- Portfolio VaR step, news sentiment, full DAG branching
- Scheduler integration (v2)
