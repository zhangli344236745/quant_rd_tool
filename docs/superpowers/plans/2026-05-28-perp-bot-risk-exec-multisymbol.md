# Perp Bot Risk+Exec+MultiSymbol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Binance USDT-M perpetual bot into a safer, production-like system: per-trade SL/TP (native conditional orders with soft fallback), deterministic idempotency via `clientOrderId` keyed by `(symbol, bar_end, target_side)`, multi-symbol portfolio runner, and persistent state/telemetry.

**Architecture:** Keep signal generation unchanged (`analyze_crypto → combined_signal`). Add a Risk Engine (position sizing + SL/TP + circuit breaker) and Execution Engine (flip sequencing, order placement, protection placement & reconciliation, idempotency). A Portfolio Runner loops symbols and enforces global exposure constraints. Persist state to disk for de-dupe and protection fail streaks.

**Tech Stack:** Python (uv), ccxt (binance futures), FastAPI, argparse CLI, pytest.

---

## File Structure (lock-in)

**Create**
- `src/quant_rd_tool/perp_models.py` — shared dataclasses/enums for perp bot cycles (targets, plans, order refs)
- `src/quant_rd_tool/perp_risk.py` — Risk Engine: sizing + SL/TP + circuit breaker
- `src/quant_rd_tool/perp_exec.py` — Execution Engine: idempotency + entry/exit/protection placement + reconcile
- `src/quant_rd_tool/perp_portfolio.py` — Multi-symbol runner orchestration + global constraints
- `src/quant_rd_tool/perp_state.py` — richer persistent state (extends current `TradingState` usage; keep `TradingState` for generic use)
- `src/quant_rd_tool/perp_telemetry.py` — structured JSONL logging + optional notifier interface (no-op default)

**Modify**
- `src/quant_rd_tool/binance_perp_bot.py` — adapt to use risk/exec engines; keep current single-symbol CLI/API compatibility
- `src/quant_rd_tool/cli.py` — add `quant-rd crypto perp-portfolio ...` (multi-symbol) and extend `perp-bot` flags for SL/TP config
- `src/quant_rd_tool/routes/crypto.py` — add `POST /api/v1/crypto/perp-portfolio/run` (run-once multi-symbol)
- `README.md` — document new CLI/API usage

**Test**
- `tests/test_perp_client_order_id.py`
- `tests/test_perp_risk_sl_tp.py`
- `tests/test_perp_exec_protection_contract.py`
- `tests/test_perp_portfolio_constraints.py`
- `tests/test_cli_crypto_perp_portfolio.py`

Reference spec:
- `docs/superpowers/specs/2026-05-28-perp-bot-risk-exec-multisymbol-design.md`

---

### Task 1: Deterministic `clientOrderId` + constraints

**Files:**
- Create: `src/quant_rd_tool/perp_models.py`
- Test: `tests/test_perp_client_order_id.py`

- [ ] **Step 1: Write failing tests for clientOrderId**

```python
from quant_rd_tool.perp_models import build_client_order_id

def test_client_order_id_deterministic():
    a = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="long")
    b = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="long")
    assert a == b

def test_client_order_id_changes_with_side():
    a = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="long")
    b = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="short")
    assert a != b

def test_client_order_id_length_and_charset():
    cid = build_client_order_id(symbol="BTC/USDT:USDT", bar_end="2026-05-28 14:30:00", target_side="long")
    assert len(cid) <= 36
    assert cid.replace("-", "").replace("_", "").isalnum()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_client_order_id.py`  
Expected: FAIL (missing module/functions)

- [ ] **Step 3: Implement minimal `perp_models.build_client_order_id`**

Requirements:
- Key: `(symbol, bar_end, target_side)` (confirmed)
- Output length ≤ 36, charset `[A-Za-z0-9_-]`
- Use stable hash (e.g., sha1 → base32/hex trimmed) with readable prefix like `qrdp_`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_perp_client_order_id.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/perp_models.py tests/test_perp_client_order_id.py
git commit -m "$(cat <<'EOF'
feat: add deterministic clientOrderId builder for perp bot

Generate stable short IDs keyed by (symbol, bar_end, target_side) for idempotent execution.
EOF
)"
```

---

### Task 2: Risk Engine v1 (sizing + SL/TP pricing + circuit breaker)

**Files:**
- Create: `src/quant_rd_tool/perp_risk.py`
- Test: `tests/test_perp_risk_sl_tp.py`

- [ ] **Step 1: Write failing tests for SL/TP computation**

```python
from quant_rd_tool.perp_risk import compute_sl_tp_prices

def test_sl_tp_long_pct():
    sl, tp = compute_sl_tp_prices(side="long", ref_price=100.0, sl_pct=0.01, tp_pct=0.02)
    assert sl == 99.0
    assert tp == 102.0

def test_sl_tp_short_pct():
    sl, tp = compute_sl_tp_prices(side="short", ref_price=100.0, sl_pct=0.01, tp_pct=0.02)
    assert sl == 101.0
    assert tp == 98.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_risk_sl_tp.py`  
Expected: FAIL

- [ ] **Step 3: Implement minimal risk functions**

Minimum API:
- `compute_notional(free_usdt, total_risk_fraction, confidence, min_conf, max_conf, max_per_symbol_notional)`
- `compute_sl_tp_prices(side, ref_price, sl_pct, tp_pct)` (pct mode)
- `CircuitBreakerState` + `should_block_trading(...)` based on daily loss pct (wallet-based)

Also add rounding helpers (tick rounding will be implemented in Task 4 with exchange market info).

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_perp_risk_sl_tp.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/perp_risk.py tests/test_perp_risk_sl_tp.py
git commit -m "$(cat <<'EOF'
feat: add perp risk engine primitives (sizing and SL/TP)

Provide initial notional sizing, pct-based SL/TP computation, and circuit-breaker scaffolding.
EOF
)"
```

---

### Task 2b: Volatility/ATR proxy (for sizing + SL/TP)

**Files:**
- Modify: `src/quant_rd_tool/perp_risk.py`
- Test: `tests/test_perp_risk_atr.py`

- [ ] **Step 1: Write failing test for ATR**

```python
import pandas as pd
from quant_rd_tool.perp_risk import compute_atr

def test_atr_basic():
    df = pd.DataFrame(
        {
            "high": [10, 11, 12],
            "low": [9, 10, 11],
            "close": [9.5, 10.5, 11.5],
        }
    )
    atr = compute_atr(df, period=2)
    assert atr > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_risk_atr.py`  
Expected: FAIL

- [ ] **Step 3: Implement `compute_atr` + ATR-multiple SL/TP option**

Requirements:
- `compute_atr(df, period)` returns latest ATR float
- Add `compute_sl_tp_prices_atr(side, ref_price, atr, sl_atr, tp_atr)` and validate ordering

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_perp_risk_atr.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/perp_risk.py tests/test_perp_risk_atr.py
git commit -m "$(cat <<'EOF'
feat: add ATR volatility proxy for perp risk engine

Compute ATR from recent OHLCV to support volatility-aware sizing and SL/TP.
EOF
)"
```

---

### Task 3: Persistent perp state (protection fail streak + order refs)

**Files:**
- Create: `src/quant_rd_tool/perp_state.py`
- Modify: `src/quant_rd_tool/trading_state.py` (only if shared helpers needed)
- Test: `tests/test_perp_state_rich.py`

- [ ] **Step 1: Write failing test for protection_fail_streak persistence**

```python
from quant_rd_tool.perp_state import PerpSymbolState

def test_fail_streak_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    s = PerpSymbolState(symbol="BTC/USDT:USDT", protection_fail_streak=2)
    s.save(p)
    out = PerpSymbolState.load(p)
    assert out.protection_fail_streak == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_state_rich.py`  
Expected: FAIL

- [ ] **Step 3: Implement `PerpSymbolState`**

Fields (minimum):
- `symbol`
- `last_seen_bar_end`
- `last_target_side`
- `position_snapshot` (side/amount/entry_price optional)
- `protection_fail_streak`
- `sl_order` / `tp_order` refs: `{clientOrderId, exchangeOrderId, stopPrice, status}`
 - `daily_start_usdt_total` (for circuit breaker)
 - `daily_date` (YYYY-MM-DD) and `last_checked_at`

- [ ] **Step 4: Run test**

Run: `uv run pytest -q tests/test_perp_state_rich.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/perp_state.py tests/test_perp_state_rich.py
git commit -m "$(cat <<'EOF'
feat: add rich perp state persistence for protection tracking

Persist per-symbol protection streak and order references for reconciliation.
EOF
)"
```

---

### Task 4: Execution Engine v1 (native SL/TP with soft fallback + N-strike force close)

**Files:**
- Create: `src/quant_rd_tool/perp_exec.py`
- Modify: `src/quant_rd_tool/binance_perp_bot.py`
- Test: `tests/test_perp_exec_protection_contract.py`

- [ ] **Step 1: Write failing tests for protection contract logic**

```python
from quant_rd_tool.perp_exec import ProtectionResult, should_force_close_on_protection_fail

def test_force_close_after_n_failures():
    assert should_force_close_on_protection_fail(fail_streak=0, max_failures=3) is False
    assert should_force_close_on_protection_fail(fail_streak=2, max_failures=3) is False
    assert should_force_close_on_protection_fail(fail_streak=3, max_failures=3) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_exec_protection_contract.py`  
Expected: FAIL

- [ ] **Step 3: Implement execution primitives (logic only)**

Minimum functions (pure logic, testable without exchange):
- Build entry + SL + TP order intents (types/sides/stopPrice/reduceOnly)
- Decide protection outcome & update `protection_fail_streak` per spec C

Then add exchange adapter functions (best-effort):
- `place_native_sl_tp(ex, symbol, amount, sl_price, tp_price, client_order_id_prefix, trigger_source="last")`
  - Must pass `stopPrice` in params for STOP_MARKET and TAKE_PROFIT_MARKET
  - Must attach `newClientOrderId` in params (binance futures; enforce <=36 and charset)
  - Must set `reduceOnly=True`
  - Return order refs or raise with categorized error
- On failure: mark soft protection active in state

Define trigger source mapping:
- for now default `last`, but code should accept a `trigger_source` param for future switch
  - Pin `workingType` param explicitly:
    - `last` -> `CONTRACT_PRICE`
    - `mark` -> `MARK_PRICE`

- [ ] **Step 3b: Add reconcile/cancel/replace protection orders**

Requirements:
- Each cycle, fetch open orders/conditional orders best-effort and:
  - if missing SL or TP while position open -> attempt re-place and increment fail streak on failure
  - on flip/close -> cancel stale protection orders for the old side
  - if fail streak reaches N -> force close reduceOnly market and clear protection state


- [ ] **Step 4: Wire into `BinancePerpBot`**

Modify `run_once/_execute_cycle` flow:
- After open, attempt `place_native_sl_tp`
- If fails: increment streak and enable soft protection
- If streak reaches N: force close reduceOnly market and clear position state

- [ ] **Step 5: Run unit tests**

Run: `uv run pytest -q tests/test_perp_exec_protection_contract.py`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/quant_rd_tool/perp_exec.py src/quant_rd_tool/binance_perp_bot.py tests/test_perp_exec_protection_contract.py
git commit -m "$(cat <<'EOF'
feat: add protection order engine with soft fallback and force-close policy

Place native SL/TP when possible; fallback to soft protection and force-close after N failures.
EOF
)"
```

---

### Task 5: Multi-symbol Portfolio Runner + constraints

**Files:**
- Create: `src/quant_rd_tool/perp_portfolio.py`
- Test: `tests/test_perp_portfolio_constraints.py`

- [ ] **Step 1: Write failing tests for constraints**

```python
from quant_rd_tool.perp_portfolio import allocate_notional

def test_allocate_respects_max_per_symbol():
    alloc = allocate_notional(symbols=["BTC","ETH"], total_notional=1000, max_per_symbol=400)
    assert alloc["BTC"] <= 400
    assert alloc["ETH"] <= 400

def test_allocate_respects_total_budget():
    alloc = allocate_notional(symbols=["BTC","ETH"], total_notional=500, max_per_symbol=400)
    assert sum(alloc.values()) <= 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_portfolio_constraints.py`  
Expected: FAIL

- [ ] **Step 3: Implement runner skeleton**

Minimum:
- `allocate_notional(...)` (simple equal-weight + cap)
- `run_portfolio_once(symbols, config, ...)` returning per-symbol cycle results
- Share one authenticated exchange instance per run (reduce overhead/rate limits)
 - Enforce:
   - `max_total_exposure_usdt`
   - `max_concurrent_positions`

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_perp_portfolio_constraints.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/perp_portfolio.py tests/test_perp_portfolio_constraints.py
git commit -m "$(cat <<'EOF'
feat: add multi-symbol perp portfolio runner skeleton

Introduce portfolio-level notional allocation with per-symbol caps and run-once orchestration.
EOF
)"
```

---

### Task 6: CLI + API for portfolio run-once

**Files:**
- Modify: `src/quant_rd_tool/cli.py`
- Modify: `src/quant_rd_tool/routes/crypto.py`
- Test: `tests/test_cli_crypto_perp_portfolio.py`
- Update: `README.md`

- [ ] **Step 1: CLI help test**

```python
import subprocess

def test_crypto_perp_portfolio_help():
    p = subprocess.run(["uv","run","quant-rd","crypto","perp-portfolio","--help"], capture_output=True, text=True)
    assert p.returncode == 0
```

- [ ] **Step 2: Implement `quant-rd crypto perp-portfolio`**

Args:
- `--symbols BTC ETH`
- risk flags: `--sl-pct --tp-pct --max-daily-loss-pct --total-risk-fraction --max-per-symbol-notional`
- exec flags: `--native-protection/--no-native-protection`, `--max-protection-failures`
- `--once` only for now (future: loop)

- [ ] **Step 3: Add API endpoint**

`POST /api/v1/crypto/perp-portfolio/run` returning `{results:[...]}`

- [ ] **Step 4: Run tests + docs**

Run: `uv run pytest -q tests/test_cli_crypto_perp_portfolio.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/cli.py src/quant_rd_tool/routes/crypto.py tests/test_cli_crypto_perp_portfolio.py README.md
git commit -m "$(cat <<'EOF'
feat: add perp portfolio CLI and API run-once

Expose multi-symbol runner with risk/exec configuration via CLI and FastAPI.
EOF
)"
```

---

### Task 7: Telemetry (JSONL) + decision enums

**Files:**
- Create: `src/quant_rd_tool/perp_telemetry.py`
- Modify: `src/quant_rd_tool/binance_perp_bot.py` and/or portfolio runner
- Test: `tests/test_perp_telemetry_jsonl.py`

- [ ] **Step 1: Implement JSONL writer with stable schema**

Emit per-symbol cycle summary:
- `decision ∈ {skipped_dedup, blocked_circuit_breaker, opened, flipped, closed, no_op, error}`
- include `error_category ∈ {transient, exchange_reject, config, unknown}`

- [ ] **Step 2: Add minimal tests and run full suite**

Run: `uv run pytest -q`  
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/quant_rd_tool/perp_telemetry.py tests/test_perp_telemetry_jsonl.py src/quant_rd_tool/binance_perp_bot.py
git commit -m "$(cat <<'EOF'
feat: add perp telemetry JSONL cycle summaries

Write structured per-symbol decisions for debugging and alerting integration.
EOF
)"
```

---

## Plan Review Loop

After this plan is saved, run a plan-document review agent against:
- Plan: `docs/superpowers/plans/2026-05-28-perp-bot-risk-exec-multisymbol.md`
- Spec: `docs/superpowers/specs/2026-05-28-perp-bot-risk-exec-multisymbol-design.md`

Then incorporate feedback before execution.

