# Crypto Options Strike Probability Panel — Design Spec

**Approved:** 2026-05-30  
**Parent:** [Crypto Options Volatility](./2026-05-30-crypto-options-volatility-design.md)  
**Data sources:** Binance Options (EAPI) + spot OHLCV + qlib ML  
**Delivery:** API + Vue panel on `CryptoOptionsVolView` only (no AnalyzeView embed in MVP)

## Goals

For a selected underlying (BTC, ETH, …), show an **ATM ±N strike ladder** with:

1. **Expiry ITM probability** — \(P(S_T \ge K)\) for calls (spot at or above strike at expiry).
2. **Touch probability** — \(P(\exists t \in [0,T]: S_t \ge K)\) during the option life (upward touch, call-oriented).
3. **Dual-track comparison** on each row:
   - **Model (qlib + GBM)** — historical vol + qlib predicted return as drift.
   - **Implied (risk-neutral)** — per-strike `markIV` from Binance via Black–Scholes digital / \(N(d_2)\), \(r \approx 0\).

Help users see where **model belief** diverges from **options market pricing**.

## User decisions (locked)

| Topic | Choice |
|-------|--------|
| Probability types | Expiry ITM **and** touch (both) |
| Strike scope | ATM ±N (default N=5), not full chain in MVP |
| Probability display | Model vs implied side-by-side |
| UI surface | **Only** `CryptoOptionsVolView` (lazy load on row select) |
| Put columns | P2 (MVP: call-oriented ITM / upward touch only) |

## Non-goals (MVP)

- Full option chain toggle (P2: “expand full chain”).
- AnalyzeView embedded panel.
- Auto-trading from probability edge.
- Put-side symmetric table (documented as follow-up).
- Historical empirical touch rate as primary metric (optional P2 footnote).

## Architecture

| Module | Responsibility |
|--------|----------------|
| `crypto_options_strike_probs.py` | Ladder build, GBM model probs, BS implied probs, report assembly |
| `crypto_options_data.py` | Reuse `fetch_mark_rows`, `parse_option_symbol`, index price |
| `crypto_ml.py` / `qlib_ml.py` | Reuse `run_crypto_ml_analysis` for drift (`predicted_return`) |
| `ccxt_data` + crypto storage | Spot OHLCV for realized volatility |
| `routes/crypto.py` | `GET /options/strike-probability` |
| `CryptoOptionsVolView.vue` | Strike probability table card |

```text
User selects row in scan table
  → GET /api/v1/crypto/options/strike-probability?base=BTC&n=5
  → EAPI marks + index
  → Load spot OHLCV (existing crypto data dir)
  → Optional: run_crypto_ml_analysis (if bars sufficient)
  → build_strike_probability_report
  → JSON rows for UI table
```

## Math (MVP)

### Shared inputs

- \(S_0\) — index / spot from EAPI.
- \(T\) — time to expiry in years (`dte / 365`).
- Per strike \(K\) — ladder from marks; `markIV` for implied leg.

### Model leg (physical / forecast approximate)

- **Volatility** \(\sigma\): annualized realized vol from spot log returns (e.g. 30–60d window, configurable).
- **Drift** \(\mu\): scale qlib `latest.predicted_return` (one-bar proxy) to horizon:
  - \(\mu_{\text{ann}} \approx \hat{r} \times (\text{bars per year} / \text{bars per prediction horizon})\), capped to sane bounds.
- Assume GBM: \(\ln S_T \sim \mathcal{N}(\ln S_0 + (\mu - \frac{1}{2}\sigma^2)T,\ \sigma^2 T)\).

**Expiry call ITM:**

\[
P_{\text{model}}(S_T \ge K) = 1 - \Phi\left(\frac{\ln(K/S_0) - (\mu - \frac{1}{2}\sigma^2)T}{\sigma\sqrt{T}}\right)
\]

**Touch (upward, call-oriented):**

Use standard GBM one-sided barrier approximation (document formula in code comments; unit tests against reference values). If \(K \le S_0\), touch prob = 1 for upward touch.

### Implied leg (risk-neutral)

Per strike: IV = `markIV` from EAPI row (call preferred; fallback put same strike/expiry).

**Expiry:**

\[
P_{\text{implied}}(S_T \ge K) = N(d_2), \quad r = 0
\]

**Touch (implied):** MVP may show `null` / `—` with tooltip “仅模型腿提供触达；隐含触达需曲面/数值方法”. Do not fabricate from ATM IV alone without documenting assumption.

### Divergence column

`model_expiry_itm - implied_expiry_itm` (percentage points) for quick scan.

## Strike ladder

1. Resolve **expiry** from the same near-month contract as volatility scan (`pick_atm_contract` logic / scan row `expiry`).
2. Filter `marks` for `base` + that expiry (YYMMDD).
3. Sort strikes; find ATM = strike minimizing \(|K - S_0|\).
4. Take N strikes below and N above ATM (2N+1 rows). If fewer exist, return available + `warnings`.

Config in `data/settings.json`:

```json
{
  "crypto_options_strike_probs": {
    "default_n": 5,
    "min_dte": 7,
    "vol_lookback_days": 30,
    "cache_seconds": 60
  }
}
```

## API

### `GET /api/v1/crypto/options/strike-probability`

| Query | Description |
|-------|-------------|
| `base` | Required, e.g. `BTC` |
| `n` | Optional, default from settings (5) |
| `data_dir` | Default `data/crypto` |
| `expiry` | Optional ISO date; default = scan ATM expiry for base |

**Response (shape):**

```json
{
  "base": "BTC",
  "spot": 95000.0,
  "expiry": "2026-06-27T00:00:00+00:00",
  "dte": 28.5,
  "n": 5,
  "model": {
    "enabled": true,
    "sigma_ann": 0.55,
    "mu_ann": 0.08,
    "qlib": { "signal": "模型偏多", "predicted_return": 0.002 },
    "assumptions": "GBM; realized vol + qlib drift"
  },
  "rows": [
    {
      "strike": 90000,
      "side": "C",
      "symbol": "BTC-260627-90000-C",
      "moneyness_pct": -5.26,
      "mark_iv": 0.52,
      "model": { "expiry_itm_call": 0.68, "touch_call": 0.82 },
      "implied": { "expiry_itm_call": 0.71, "touch_call": null },
      "edge_expiry": -0.03
    }
  ],
  "warnings": [],
  "disclaimer": "研究用途。模型概率与期权隐含概率口径不同，不构成投资建议。"
}
```

**Errors:**

- `503` — EAPI unreachable.
- `200` with `model.enabled: false` + `reason` when qlib/OHLCV insufficient; implied columns still populated when marks exist.

**Caching:** In-process TTL keyed by `(base, n, expiry)` for `cache_seconds`.

## Frontend (`CryptoOptionsVolView.vue`)

- On table row click (existing `selectedBase`), fire lazy `GET strike-probability`.
- New card: **「行权价概率 · {base}」** below advice / beside snapshot (responsive stack on narrow).
- Columns: Strike | Moneyness % | Mark IV | Model P(expiry) | Implied P(expiry) | Model P(touch) | Edge.
- Loading skeleton; error alert; empty qlib → banner with reason, implied table still visible.
- Footer: disclaimer + link to assumptions text.

**Types:** extend `src/quant_trade_tool/src/api/crypto.ts`.

## CLI (optional P2)

`uv run quant-rd crypto options-strikes --symbol BTC --n 5` — JSON to stdout for debugging. Not required for MVP if API exists.

## Testing

| Test | Intent |
|------|--------|
| `test_strike_ladder_atm_n` | 2N+1 strikes, sorted, correct expiry filter |
| `test_model_expiry_prob` | Known BS/GBM inputs → expected Φ |
| `test_implied_expiry_prob` | Fixed IV/spot/dte → N(d2) |
| `test_touch_monotonicity` | Higher strike → lower touch prob |
| `test_api_strike_probability` | Mock EAPI + OHLCV fixture |
| `test_qlib_skipped_implied_ok` | model disabled, rows still have implied |

## Security & compliance

- No new secrets; same EAPI public endpoints as vol scan.
- Prominent **non-advisory** disclaimer on panel and API field.

## Implementation order (for writing-plans)

1. `crypto_options_strike_probs.py` + unit tests (pure math/ladder).
2. Wire OHLCV + qlib in report builder.
3. API route + settings defaults.
4. Frontend table + API client.
5. README section under crypto options.

## P2 backlog

- Put ITM / downward touch columns.
- Full chain expand toggle.
- Implied touch via local vol or flat skew adjustment (documented).
- CLI command.
- Embed compact widget in AnalyzeView.
