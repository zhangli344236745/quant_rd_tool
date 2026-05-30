# Binance Perp Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `BinancePerpBot` into a position-aware Binance USDT-M perpetual futures bot that runs every 10 minutes, flips positions one-way (close then open), sizes orders by `amount` with precision/min-notional checks, persists de-dupe state, and exposes both API + CLI entrypoints.

**Architecture:** Keep the existing signal pipeline (`analyze_crypto → combined_signal`) unchanged. Implement a futures execution layer inside `binance_perp_bot.py` that (1) fetches futures balance + positions, (2) validates one-way mode, (3) computes target side, (4) closes then opens with market orders using `amount`, (5) persists a lightweight state file to prevent duplicate trades on the same bar. Wire it into CLI (`quant-rd crypto perp-bot ...`) and keep the existing FastAPI route.

**Tech Stack:** Python 3.12 (uv), ccxt (Binance futures), FastAPI, argparse CLI.

---

### Task 1: Define normalized position + state persistence

**Files:**
- Modify: `src/quant_rd_tool/binance_perp_bot.py`
- Create: `src/quant_rd_tool/trading_state.py`
- Test: `tests/test_perp_state.py`

- [ ] **Step 1: Write failing test for state load/save**

```python
from quant_rd_tool.trading_state import TradingState

def test_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    s = TradingState(last_seen_bar_end="2026-01-01 00:10:00", last_action="long")
    s.save(p)
    out = TradingState.load(p)
    assert out.last_seen_bar_end == "2026-01-01 00:10:00"
    assert out.last_action == "long"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_state.py`  
Expected: FAIL (`ModuleNotFoundError: trading_state` or missing `TradingState`)

- [ ] **Step 3: Implement minimal `TradingState`**

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

@dataclass
class TradingState:
    last_seen_bar_end: str = ""
    last_action: str = ""

    @staticmethod
    def load(path: str | Path) -> "TradingState":
        p = Path(path)
        if not p.exists():
            return TradingState()
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
        return TradingState(
            last_seen_bar_end=str(data.get("last_seen_bar_end") or ""),
            last_action=str(data.get("last_action") or ""),
        )

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {"last_seen_bar_end": self.last_seen_bar_end, "last_action": self.last_action},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_perp_state.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/trading_state.py tests/test_perp_state.py
git commit -m "$(cat <<'EOF'
feat: add trading state persistence

Persist last seen bar end to prevent duplicate trades across restarts.
EOF
)"
```

---

### Task 2: Normalize futures position fetching (one-way only)

**Files:**
- Modify: `src/quant_rd_tool/binance_perp_bot.py`
- Test: `tests/test_perp_position_normalize.py`

- [ ] **Step 1: Write failing test for position normalization**

```python
from quant_rd_tool.binance_perp_bot import _normalize_position_rows

def test_normalize_flat():
    side, amt = _normalize_position_rows([{"contracts": 0.0}])
    assert side == "flat"
    assert amt == 0.0

def test_normalize_long():
    side, amt = _normalize_position_rows([{"contracts": 0.1}])
    assert side == "long"
    assert amt == 0.1

def test_normalize_short():
    side, amt = _normalize_position_rows([{"contracts": -0.2}])
    assert side == "short"
    assert amt == 0.2

def test_reject_multiple_rows():
    try:
        _normalize_position_rows([{"contracts": 0.1}, {"contracts": -0.1}])
    except ValueError as e:
        assert "hedge" in str(e).lower() or "multiple" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_position_normalize.py`  
Expected: FAIL (missing symbol/function)

- [ ] **Step 3: Implement `_normalize_position_rows` + `fetch_position` wrapper**

Implementation requirements:
- Pull `contracts` first; fallback to `info.positionAmt` (string) if needed
- Apply `position_epsilon` to treat near-zero as flat
- If multiple rows returned, raise `ValueError` indicating hedge mode not supported

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_perp_position_normalize.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/binance_perp_bot.py tests/test_perp_position_normalize.py
git commit -m "$(cat <<'EOF'
feat: add one-way futures position normalization

Normalize ccxt position rows and reject hedge/multi-leg responses.
EOF
)"
```

---

### Task 3: Implement amount sizing with precision + min-notional checks

**Files:**
- Modify: `src/quant_rd_tool/binance_perp_bot.py`
- Test: `tests/test_perp_sizing.py`

- [ ] **Step 1: Write failing test for sizing**

```python
from quant_rd_tool.binance_perp_bot import _calc_amount_from_notional

def test_calc_amount_basic():
    # notional=300 USDT, price=30000 -> 0.01 BTC
    amt = _calc_amount_from_notional(notional_usdt=300, price=30000, amount_step=0.001)
    assert amt == 0.01

def test_calc_amount_rounds_down_to_step():
    amt = _calc_amount_from_notional(notional_usdt=305, price=30000, amount_step=0.001)
    # 305/30000=0.010166.. -> floor to 0.010
    assert amt == 0.01
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_sizing.py`  
Expected: FAIL

- [ ] **Step 3: Implement sizing helpers**

Requirements:
- Prefer `ex.amount_to_precision(symbol, raw_amount)` but also enforce **step size floor**
- Compute `amount_step` from `market.limits.amount.min` or `market.precision.amount` if available; otherwise accept a safe fallback and warn
- After rounding: ensure `amount > 0` and `amount * price >= min_notional_usdt`
- If fails: return `None` (skip trade) with a reason in output

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_perp_sizing.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/binance_perp_bot.py tests/test_perp_sizing.py
git commit -m "$(cat <<'EOF'
feat: size perp orders by amount with min-notional checks

Use ticker price and market precision/limits to compute safe order amounts.
EOF
)"
```

---

### Task 4: Implement one-way flip execution (close then open)

**Files:**
- Modify: `src/quant_rd_tool/binance_perp_bot.py`
- Test: `tests/test_perp_decision.py`

- [ ] **Step 1: Write failing test for decision tree**

```python
from quant_rd_tool.binance_perp_bot import _decide_plan

def test_same_side_noop():
    plan = _decide_plan(position_side="long", target_side="long", hold_behavior="do_nothing")
    assert plan == {"close": False, "open": False}

def test_flip_closes_then_opens():
    plan = _decide_plan(position_side="long", target_side="short", hold_behavior="do_nothing")
    assert plan["close"] is True
    assert plan["open"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_decision.py`  
Expected: FAIL

- [ ] **Step 3: Implement plan + execution**

Requirements:
- Close order must be `reduceOnly=True`
- Close amount uses current abs position
- Open order uses computed amount sizing
- Return structured result: `close_order`, `open_order`, `position_before`, `target_side`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_perp_decision.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/binance_perp_bot.py tests/test_perp_decision.py
git commit -m "$(cat <<'EOF'
feat: implement one-way flip execution for perp bot

Close existing position with reduceOnly then open target direction.
EOF
)"
```

---

### Task 5: Add de-dupe + run_forever loop (10m interval)

**Files:**
- Modify: `src/quant_rd_tool/binance_perp_bot.py`
- Modify: `src/quant_rd_tool/config.py` (optional, only if adding env vars)
- Test: `tests/test_perp_dedupe.py`

- [ ] **Step 1: Write failing test for de-dupe logic**

```python
from quant_rd_tool.trading_state import TradingState
from quant_rd_tool.binance_perp_bot import _should_trade_bar

def test_dedupe_same_bar_skips():
    st = TradingState(last_seen_bar_end="2026-01-01 00:10:00", last_action="long")
    assert _should_trade_bar(st, bar_end="2026-01-01 00:10:00") is False
    assert _should_trade_bar(st, bar_end="2026-01-01 00:20:00") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_perp_dedupe.py`  
Expected: FAIL

- [ ] **Step 3: Implement stateful de-dupe + run_forever**

Requirements:
- Add `state_path` to `PerpBotConfig` defaulting to `data/crypto/perp_state_<base>.json`
- On each successful decision cycle, update and save state
- `run_forever()` catches exceptions, logs, sleeps based on `interval_minutes`

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_perp_dedupe.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/trading_state.py src/quant_rd_tool/binance_perp_bot.py tests/test_perp_dedupe.py
git commit -m "$(cat <<'EOF'
feat: add perp bot dedupe state and run loop

Persist last seen bar end and run every N minutes with retry-safe loop.
EOF
)"
```

---

### Task 6: Add CLI entrypoint `quant-rd crypto perp-bot`

**Files:**
- Modify: `src/quant_rd_tool/cli.py`
- Modify: `README.md` (optional)
- Test: `tests/test_cli_crypto_perp_bot.py`

- [ ] **Step 1: Write failing test that CLI parser recognizes command**

Implement a minimal test that imports CLI module and ensures new subcommand is wired (pattern similar to existing crypto bot tests if any; otherwise smoke test by invoking module with args in subprocess).

- [ ] **Step 2: Implement argparse subcommand**

Add `crypto_sub.add_parser("perp-bot", ...)` with args:
- `--base` (default BTC)
- `--quote` (default USDT)
- `--timeframe` (default 5m)
- `--interval-minutes` (default 10)
- `--ohlcv-limit` (default 800)
- `--leverage` (default 3)
- `--risk-fraction` (default 0.2)
- `--signal-only`
- `--live` (sets `dry_run=False`, require API keys)
- `--testnet`
- `--ccxt-symbol` override
- `--once` (run_once) vs default run_forever

Execution:
- Create `PerpBotConfig` from args + `settings.*`
- If `--once`: print `bot.run_once()` JSON
- Else: run `bot.run_forever()` and handle KeyboardInterrupt

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -q`  
Expected: PASS (existing 44 tests + new ones)

- [ ] **Step 4: Commit**

```bash
git add src/quant_rd_tool/cli.py tests/test_cli_crypto_perp_bot.py README.md
git commit -m "$(cat <<'EOF'
feat: add crypto perp-bot CLI command

Expose perpetual futures bot via quant-rd crypto perp-bot with dry-run by default.
EOF
)"
```

---

### Task 7: API response shape polish + docs update

**Files:**
- Modify: `src/quant_rd_tool/routes/crypto.py`
- Modify: `README.md`

- [ ] **Step 1: Ensure API returns structured orders**

Update `crypto_perp_bot_run` output expectation:
- `signal`, `target_side`, `position_before`, `close_order`, `open_order`, `message`, `error`

- [ ] **Step 2: Update README usage examples**

Add examples for:
- `curl` dry-run `signal_only`
- CLI run once vs forever

- [ ] **Step 3: Run full tests**

Run: `uv run pytest -q`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/quant_rd_tool/routes/crypto.py README.md
git commit -m "$(cat <<'EOF'
docs: document perp bot API and CLI

Clarify response fields and add usage examples for perp trading bot.
EOF
)"
```

