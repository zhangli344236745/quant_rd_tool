# Crypto News Sentiment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest free RSS macro/crypto news, score with rules, LLM-advise top items, schedule independently or attach digest to analysis cycles, expose API + Vue page + Bark alerts.

**Architecture:** Focused modules under `crypto_news_*.py`; extend `scheduler_manager` with `job_type=news`; reuse `schedule_alerts` delivery and `research.py`-style LLM calls (sync).

**Tech Stack:** Python 3.11+, feedparser, httpx, FastAPI, pytest; Vue 3 + Element Plus.

**Spec:** `docs/superpowers/specs/2026-06-03-crypto-news-sentiment-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| `src/quant_rd_tool/crypto_news_feeds.py` | RSS fetch + normalize |
| `src/quant_rd_tool/crypto_news_scoring.py` | Rule-based impact score |
| `src/quant_rd_tool/crypto_news_advisor.py` | LLM + template fallback |
| `src/quant_rd_tool/crypto_news_storage.py` | JSONL + digest + state |
| `src/quant_rd_tool/crypto_news_pipeline.py` | Full cycle orchestration |
| `src/quant_rd_tool/crypto_news_config.py` | settings.json section |
| `src/quant_rd_tool/crypto_news_scheduler.py` | `run_news_cycle()` |
| `tests/test_crypto_news_feeds.py` | RSS parse tests |
| `tests/test_crypto_news_scoring.py` | Scoring tests |
| `tests/test_crypto_news_pipeline.py` | End-to-end with mocks |
| `src/quant_rd_tool/scheduler_manager.py` | `job_type` news branch |
| `src/quant_rd_tool/crypto_scheduler.py` | attach digest |
| `src/quant_rd_tool/schedule_alerts.py` | high-impact news alert |
| `src/quant_rd_tool/routes/crypto.py` | REST routes |
| `src/quant_trade_tool/src/views/CryptoNewsView.vue` | Main UI |
| `src/quant_trade_tool/src/api/crypto.ts` | API client |
| `src/quant_trade_tool/src/router/index.ts` | `/crypto-news` |
| `src/quant_trade_tool/src/layouts/MainLayout.vue` | Nav |
| `src/quant_trade_tool/src/views/SchedulesView.vue` | News job type |
| `src/quant_trade_tool/src/views/AnalyzeView.vue` | Digest card |
| `pyproject.toml` | feedparser dep |

---

### Task 1: Dependency + feed parsing (TDD)

**Files:**
- Modify: `pyproject.toml`
- Create: `src/quant_rd_tool/crypto_news_feeds.py`
- Create: `tests/test_crypto_news_feeds.py`

- [ ] **Step 1:** Add `feedparser>=6.0.11` to dependencies; `uv sync`
- [ ] **Step 2:** Write failing test parsing fixture RSS XML → list of `{id, title, link, published, summary, source_id}`
- [ ] **Step 3:** Implement `DEFAULT_FEEDS`, `fetch_feed_items(feed, *, timeout=15)`, `fetch_all_feeds(feeds)`
- [ ] **Step 4:** `pytest tests/test_crypto_news_feeds.py -q` → PASS

---

### Task 2: Rule scoring (TDD)

**Files:**
- Create: `src/quant_rd_tool/crypto_news_scoring.py`
- Create: `tests/test_crypto_news_scoring.py`

- [ ] **Step 1:** Test `score_news_item({"title": "Fed raises rates", "summary": "..."})` → score ≥ 40, category `macro`
- [ ] **Step 2:** Test BTC mention boost; test below-threshold neutral item
- [ ] **Step 3:** Implement `score_news_item`, `rank_candidates(items, *, min_score, top_n)`
- [ ] **Step 4:** `pytest tests/test_crypto_news_scoring.py -q` → PASS

---

### Task 3: Storage + config

**Files:**
- Create: `src/quant_rd_tool/crypto_news_storage.py`
- Create: `src/quant_rd_tool/crypto_news_config.py`
- Create: `tests/test_crypto_news_storage.py`

- [ ] **Step 1:** Test append item to JSONL, load digest, dedupe state by url hash
- [ ] **Step 2:** Implement paths under `data/crypto/news/`
- [ ] **Step 3:** `get_crypto_news_config()` / defaults from `settings.json` section `crypto_news`
- [ ] **Step 4:** Tests PASS

---

### Task 4: LLM advisor (TDD)

**Files:**
- Create: `src/quant_rd_tool/crypto_news_advisor.py`
- Create: `tests/test_crypto_news_advisor.py`

- [ ] **Step 1:** Test template fallback when no API key
- [ ] **Step 2:** Test mock LLM returns parsed JSON merged into item
- [ ] **Step 3:** Implement `advise_items(items, *, top_n)` sync httpx like `research.py`
- [ ] **Step 4:** Tests PASS

---

### Task 5: Pipeline + manual scan

**Files:**
- Create: `src/quant_rd_tool/crypto_news_pipeline.py`
- Create: `src/quant_rd_tool/crypto_news_scheduler.py`
- Create: `tests/test_crypto_news_pipeline.py`

- [ ] **Step 1:** Test full cycle with mocked feeds + LLM writes `latest_digest.json`
- [ ] **Step 2:** Implement `run_news_scan(*, data_dir, config)` 
- [ ] **Step 3:** `run_news_cycle()` wrapper for scheduler
- [ ] **Step 4:** Tests PASS

---

### Task 6: Scheduler job_type=news

**Files:**
- Modify: `src/quant_rd_tool/scheduler_manager.py`
- Modify: `tests/test_scheduler_manager.py` (if exists) or add `tests/test_crypto_news_scheduler.py`

- [ ] **Step 1:** Add `job_type: Literal["analysis","news"] = "analysis"` to `ScheduleJobConfig`
- [ ] **Step 2:** In worker loop: if `news` → `run_news_cycle()` else existing `run_scheduled_cycle()`
- [ ] **Step 3:** Persist/load `job_type` in `schedules.json`
- [ ] **Step 4:** Test news job runs mocked pipeline once

---

### Task 7: Attach digest to analysis cycle

**Files:**
- Modify: `src/quant_rd_tool/crypto_scheduler.py`
- Modify: `tests/test_crypto_news_pipeline.py`

- [ ] **Step 1:** Test `attach_news_digest(report)` adds field when digest fresh
- [ ] **Step 2:** Call after each symbol report in `run_scheduled_cycle` when config enabled
- [ ] **Step 3:** Tests PASS

---

### Task 8: REST API

**Files:**
- Modify: `src/quant_rd_tool/routes/crypto.py`

- [ ] **Step 1:** `GET /crypto/news/digest`, `GET /crypto/news/items`, `POST /crypto/news/scan`
- [ ] **Step 2:** `GET/POST /crypto/news/config`
- [ ] **Step 3:** TestClient smoke tests

---

### Task 9: Schedule alerts (high impact)

**Files:**
- Modify: `src/quant_rd_tool/schedule_alerts.py`
- Modify: `tests/test_schedule_alerts.py`

- [ ] **Step 1:** After pipeline, `evaluate_news_alerts(digest)` if score/confidence thresholds
- [ ] **Step 2:** Wire from `run_news_cycle`
- [ ] **Step 3:** Tests with mock Bark

---

### Task 10: Frontend

**Files:**
- Create: `src/quant_trade_tool/src/views/CryptoNewsView.vue`
- Modify: `api/crypto.ts`, `router/index.ts`, `MainLayout.vue`, `SchedulesView.vue`, `AnalyzeView.vue`

- [ ] **Step 1:** API types + `cryptoApi.news*`
- [ ] **Step 2:** CryptoNewsView timeline + manual scan button
- [ ] **Step 3:** SchedulesView: job type selector「舆论扫描」
- [ ] **Step 4:** AnalyzeView digest card
- [ ] **Step 5:** Nav link「舆论雷达」

---

### Task 11: Docs + README

**Files:**
- Modify: `README.md`
- Create or extend: `docs/crypto-news.md` (optional short user guide)

- [ ] Document API, config, schedule types, disclaimer
- [ ] `.env.example` optional `CRYPTO_NEWS_*`

---

### Task 12: Verification

- [ ] `uv run pytest tests/test_crypto_news*.py tests/test_schedule_alerts.py -q`
- [ ] Manual: `POST /crypto/news/scan` → digest populated
- [ ] Manual: create news schedule job → run once → Bark if high impact

---

## Execution handoff

Plan saved. Choose:

1. **Subagent-Driven** — fresh subagent per task, review between tasks  
2. **Inline Execution** — implement in this session with checkpoints

Which approach?
