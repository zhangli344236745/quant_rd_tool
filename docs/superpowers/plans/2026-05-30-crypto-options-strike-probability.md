# Crypto Options Strike Probability — Implementation Plan

> **Status:** Implemented (2026-05-30)

**Goal:** ATM±N strike ladder with model (qlib+GBM) vs implied (IV) expiry/touch probabilities on `CryptoOptionsVolView`.

**Architecture:** `crypto_options_strike_probs.py` + `GET /options/strike-probability` + Vue lazy table.

## Delivered

- [x] `crypto_options_strike_probs.py` — ladder, GBM probs, BS implied, report + cache
- [x] `tests/test_crypto_options_strike_probs.py`
- [x] `routes/crypto.py` endpoint
- [x] `CryptoOptionsVolView.vue` + `api/crypto.ts`
- [x] README API line
- [x] Spec: `docs/superpowers/specs/2026-05-30-crypto-options-strike-probability-design.md`

## Verify

```bash
uv run pytest tests/test_crypto_options_strike_probs.py -q
uv run quant-rd serve --reload
# 期权波动页 → 选 BTC → 行权价概率表
```
