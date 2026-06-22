# Crypto Cash & Carry (Paper) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Binance spot–perp Cash & Carry scanner with manual paper position simulation, REST API, and `CryptoCarryView` UI.

**Architecture:** New backend module `crypto_carry_arbitrage.py` owns scan metrics, paper paired-leg ledger, funding accrual, and JSON persistence under `data/crypto/carry/`. Routes under `/crypto/carry/*`. Frontend page at `/crypto-carry` following existing crypto view patterns.

**Tech Stack:** Python 3.11+, ccxt (Binance spot + USDT-M), FastAPI, pytest; Vue 3 + Element Plus + axios.

**Spec:** `docs/superpowers/specs/2026-06-12-crypto-carry-arbitrage-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| `src/quant_rd_tool/crypto_carry_arbitrage.py` | Config, scan, metrics, paper open/close, funding accrual, storage |
| `tests/test_crypto_carry_arbitrage.py` | Unit tests (mocked exchange) |
| `tests/test_crypto_carry_routes.py` | API smoke tests |
| `src/quant_rd_tool/routes/crypto.py` | `/crypto/carry/*` endpoints |
| `src/quant_trade_tool/src/api/crypto.ts` | TS types + `carryScan`, `carryConfig`, etc. |
| `src/quant_trade_tool/src/views/CryptoCarryView.vue` | Full UI |
| `src/quant_trade_tool/src/router/index.ts` | Route `/crypto-carry` |
| `src/quant_trade_tool/src/layouts/MainLayout.vue` | Nav link under Crypto |

---

### Task 1: Metrics & config (TDD)

**Files:**
- Create: `src/quant_rd_tool/crypto_carry_arbitrage.py`
- Create: `tests/test_crypto_carry_arbitrage.py`

- [ ] **Step 1: Write failing tests for pure metric functions**

```python
# tests/test_crypto_carry_arbitrage.py
import pytest
from quant_rd_tool.crypto_carry_arbitrage import (
    CarryConfig,
    compute_basis_bps,
    compute_funding_apr,
    compute_composite_apr,
    entry_alert,
    exit_alert,
)


def test_compute_basis_bps():
    assert compute_basis_bps(spot_mark=100.0, perp_mark=100.5) == pytest.approx(50.0)


def test_compute_funding_apr():
    # 0.0001 per 8h -> 0.0001 * 3 * 365
    assert compute_funding_apr(0.0001) == pytest.approx(0.1095)


def test_entry_exit_alerts():
    cfg = CarryConfig(entry_threshold_apr=0.15, exit_threshold_apr=0.05)
    assert entry_alert(composite_apr=0.20, config=cfg, has_open_position=False) is True
    assert entry_alert(composite_apr=0.20, config=cfg, has_open_position=True) is False
    assert exit_alert(composite_apr=0.04, funding_rate=0.0001, config=cfg) is True
    assert exit_alert(composite_apr=0.10, funding_rate=-0.0001, config=cfg) is True
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /Users/worldunion/projects/pythonprojects/claudedemo/quant_rd_tool
uv run pytest tests/test_crypto_carry_arbitrage.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement metrics + CarryConfig + default paths**

```python
# src/quant_rd_tool/crypto_carry_arbitrage.py (excerpt)
from dataclasses import dataclass, field, asdict
from pathlib import Path

DEFAULT_WATCHLIST = ["BTC", "ETH", "SOL", "BNB"]
CARRY_DIR = Path("data/crypto/carry")

@dataclass
class CarryConfig:
    watchlist: list[str] = field(default_factory=lambda: list(DEFAULT_WATCHLIST))
    quote: str = "USDT"
    entry_threshold_apr: float = 0.15
    exit_threshold_apr: float = 0.05
    default_notional_usdt: float = 10_000.0
    spot_fee_pct: float = 0.001
    perp_fee_pct: float = 0.001
    slippage_pct: float = 0.0005
    testnet: bool = False

def compute_basis_bps(*, spot_mark: float, perp_mark: float) -> float:
    return (perp_mark - spot_mark) / spot_mark * 10_000

def compute_funding_apr(funding_rate: float) -> float:
    return funding_rate * 3 * 365

def compute_composite_apr(*, funding_apr: float, basis_bps: float) -> float:
    basis_apr_hint = basis_bps / 10_000 * 365
    return funding_apr + basis_apr_hint

def entry_alert(*, composite_apr: float, config: CarryConfig, has_open_position: bool) -> bool:
    if has_open_position:
        return False
    return composite_apr >= config.entry_threshold_apr

def exit_alert(*, composite_apr: float, funding_rate: float, config: CarryConfig) -> bool:
    return composite_apr <= config.exit_threshold_apr or funding_rate < 0
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_crypto_carry_arbitrage.py -v
```

---

### Task 2: Config load/save

**Files:**
- Modify: `src/quant_rd_tool/crypto_carry_arbitrage.py`
- Modify: `tests/test_crypto_carry_arbitrage.py`

- [ ] **Step 1: Write failing test for config persistence**

```python
def test_config_roundtrip(tmp_path, monkeypatch):
    from quant_rd_tool import crypto_carry_arbitrage as cca
    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cfg = cca.CarryConfig(watchlist=["BTC", "ETH"], entry_threshold_apr=0.12)
    cca.save_config(cfg)
    loaded = cca.load_config()
    assert loaded.watchlist == ["BTC", "ETH"]
    assert loaded.entry_threshold_apr == 0.12
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `load_config` / `save_config` reading `config.json`**

- [ ] **Step 4: Run — expect PASS**

---

### Task 3: Scan with mocked ccxt

**Files:**
- Modify: `src/quant_rd_tool/crypto_carry_arbitrage.py`
- Modify: `tests/test_crypto_carry_arbitrage.py`

- [ ] **Step 1: Write failing test**

```python
def test_scan_watchlist_builds_opportunities(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca
    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    monkeypatch.setattr(cca, "fetch_market_snapshot", lambda symbol, **kw: {
        "spot_mark": 100.0,
        "perp_mark": 100.2,
        "funding_rate": 0.0002,
    })
    cfg = cca.CarryConfig(watchlist=["BTC"])
    rows = cca.scan_watchlist(cfg)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTC"
    assert rows[0]["basis_bps"] == pytest.approx(20.0)
    assert "composite_apr" in rows[0]
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `fetch_market_snapshot` (ccxt wrapper) and `scan_watchlist`**

Use `ccxt_data.to_ccxt_symbol` for spot; perp symbol `{base}/USDT:USDT`. Call `fetch_ticker` + `fetch_funding_rate`. Handle errors per symbol (skip with error field, don't crash whole scan).

- [ ] **Step 4: Run — expect PASS**

---

### Task 4: Paper open/close PnL

**Files:**
- Modify: `src/quant_rd_tool/crypto_carry_arbitrage.py`
- Modify: `tests/test_crypto_carry_arbitrage.py`

- [ ] **Step 1: Write failing tests**

```python
def test_open_and_close_paper_carry(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca
    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    cfg = cca.CarryConfig(watchlist=["BTC"])
    pos = cca.open_paper_carry(
        "BTC",
        notional_usdt=1000.0,
        config=cfg,
        spot_mark=100.0,
        perp_mark=100.1,
        funding_rate=0.0001,
    )
    assert pos["status"] == "open"
    with pytest.raises(ValueError, match="already"):
        cca.open_paper_carry("BTC", 1000.0, config=cfg, spot_mark=100.0, perp_mark=100.1, funding_rate=0.0001)
    closed = cca.close_paper_carry(
        pos["id"],
        config=cfg,
        spot_mark=100.0,
        perp_mark=100.0,
        funding_rate=0.0001,
    )
    assert closed["status"] == "closed"
    assert closed["realized_pnl"] is not None
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `PaperCarryPosition`, `open_paper_carry`, `close_paper_carry`, `list_positions`, event append to `events.jsonl`**

Fee model: open/close both legs; slippage on entry/exit prices per spec.

- [ ] **Step 4: Run — expect PASS**

---

### Task 5: Funding accrual

**Files:**
- Modify: `src/quant_rd_tool/crypto_carry_arbitrage.py`
- Modify: `tests/test_crypto_carry_arbitrage.py`

- [ ] **Step 1: Write failing test for 8h boundary accrual**

```python
from datetime import UTC, datetime

def test_accrue_funding_on_boundary(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_carry_arbitrage as cca
    monkeypatch.setattr(cca, "CARRY_DIR", tmp_path)
    # open position, set last_funding_ts behind boundary, accrue with fixed funding_rate
    ...
    assert pos["accrued_funding"] > 0
```

- [ ] **Step 2–4: Implement `accrue_open_positions` using UTC 8h boundaries; call from `scan_watchlist`**

---

### Task 6: REST API routes

**Files:**
- Modify: `src/quant_rd_tool/routes/crypto.py`
- Create: `tests/test_crypto_carry_routes.py`

- [ ] **Step 1: Write failing route tests with TestClient + monkeypatch**

```python
def test_carry_scan_route(client, monkeypatch):
    from quant_rd_tool import crypto_carry_arbitrage as cca
    monkeypatch.setattr(cca, "scan_watchlist", lambda cfg: [{"symbol": "BTC", "composite_apr": 0.2}])
    monkeypatch.setattr(cca, "load_config", cca.CarryConfig)
    r = client.get("/api/v1/crypto/carry/scan")
    assert r.status_code == 200
    assert r.json()["items"][0]["symbol"] == "BTC"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Add Pydantic models + endpoints per spec**

- [ ] **Step 4: Run full carry tests**

```bash
uv run pytest tests/test_crypto_carry_arbitrage.py tests/test_crypto_carry_routes.py -v
```

---

### Task 7: Frontend API client

**Files:**
- Modify: `src/quant_trade_tool/src/api/crypto.ts`

- [ ] **Step 1: Add types `CarryOpportunity`, `CarryPosition`, `CarryConfig`, `CarrySummary`**

- [ ] **Step 2: Add methods**

```typescript
carryScan: () => http.get<{ items: CarryOpportunity[]; positions: CarryPosition[] }>("/crypto/carry/scan"),
carryGetConfig: () => http.get<CarryConfig>("/crypto/carry/config"),
carryPutConfig: (body: Partial<CarryConfig>) => http.put<CarryConfig>("/crypto/carry/config", body),
carryOpen: (body: { symbol: string; notionalUsdt?: number }) => http.post("/crypto/carry/positions/open", body),
carryClose: (id: string) => http.post(`/crypto/carry/positions/${id}/close`),
carrySummary: () => http.get<CarrySummary>("/crypto/carry/summary"),
```

---

### Task 8: CryptoCarryView UI

**Files:**
- Create: `src/quant_trade_tool/src/views/CryptoCarryView.vue`
- Modify: `src/quant_trade_tool/src/router/index.ts`
- Modify: `src/quant_trade_tool/src/layouts/MainLayout.vue`

- [ ] **Step 1: Add route `/crypto-carry` and nav item「Carry 套利」**

- [ ] **Step 2: Build view with four sections per spec**

  - Config bar (watchlist tags, thresholds, notional, refresh)
  - Opportunity table with entry alert tags + Open button
  - Open positions table with exit alert tags + Close button
  - Summary strip

- [ ] **Step 3: Wire `onMounted` → `carryScan` + `carryGetConfig`; manual refresh button**

- [ ] **Step 4: Disable Open when `!entry_alert || has_open_position`; confirm dialog on open/close**

---

### Task 9: Verification

- [ ] **Run backend tests**

```bash
uv run pytest tests/test_crypto_carry_arbitrage.py tests/test_crypto_carry_routes.py -v
```

Expected: all PASS.

- [ ] **Run frontend typecheck/build if available**

```bash
cd src/quant_trade_tool && npm run build
```

- [ ] **Manual smoke:** start API + dev server, open `/crypto-carry`, refresh scan, open/close paper BTC carry with mocked or live Binance public data.

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-06-12-crypto-carry-arbitrage.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — implement task-by-task in this session with checkpoints

Which approach do you want?
