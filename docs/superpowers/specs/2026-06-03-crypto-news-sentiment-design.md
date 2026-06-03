# Crypto News Sentiment & Macro Impact — Design Spec

**Approved:** 2026-06-03  
**Scope:** Free RSS/public feeds → rule scoring → LLM advice for top items; schedule + UI + Bark alerts

## Goals

1. **Periodic ingestion** of international/macro news that may move crypto prices (RSS/Atom, no paid API).
2. **Hybrid analysis:** keyword/rule scoring filters noise; top N items get LLM JSON advice (OpenAI-compatible, optional).
3. **Scheduling (S3):** independent `news` jobs on the existing scheduler **and** optional attach of latest digest to crypto analysis cycles.
4. **Actionable output:** impact direction, affected symbols, horizon, short Chinese advice (not auto-trading).
5. **Alerts:** high-impact items push via existing Bark/Webhook pipeline.

## User decisions (locked)

| Dimension | Choice |
|-----------|--------|
| Data source | **A** — Free RSS / public feeds, local fetch + keyword filter |
| Advice | **A3** — Rules first, LLM for Top N only |
| Scheduling | **S3** — Independent news job + optional merge into analysis cycle summary |

## Non-goals (MVP)

- Full-article scraping behind paywalls
- Twitter/X, Telegram, Reddit streams
- Auto-translation pipeline (titles may stay English; LLM output in Chinese)
- Auto order placement
- Paid news APIs (CryptoPanic, NewsAPI Pro)

## Architecture

### Module layout

| File | Responsibility |
|------|------------------|
| `crypto_news_feeds.py` | Default feed list, fetch RSS via `feedparser`, normalize items |
| `crypto_news_scoring.py` | Keyword rules, categories, impact score 0–100 |
| `crypto_news_advisor.py` | LLM batch for top N; template fallback without API key |
| `crypto_news_pipeline.py` | Orchestrate ingest → score → advise → persist digest |
| `crypto_news_storage.py` | JSONL items + `latest_digest.json` under `data/crypto/news/` |
| `crypto_news_scheduler.py` | `run_news_cycle()` for scheduled jobs |
| `crypto_news_config.py` | Load/save `settings.json` → `crypto_news` section |

Extend (not duplicate):

| File | Change |
|------|--------|
| `scheduler_manager.py` | `ScheduleJobConfig.job_type`: `"analysis"` \| `"news"` |
| `crypto_scheduler.py` | Optional `attach_news_digest` on analysis reports |
| `schedule_alerts.py` | `on_news_high_impact` rule + message placeholders |
| `routes/crypto.py` | REST endpoints |
| `CryptoNewsView.vue` | Timeline UI |
| `AnalyzeView.vue` / `CryptoOpsView.vue` | Compact digest card |

### Data flow

```
RSS feeds → parse → dedupe (url hash, 24h) → rule score
  → candidates (score ≥ threshold)
  → sort → top N → LLM JSON advice
  → append items.jsonl + write latest_digest.json
  → [optional] Bark if high impact
  → [optional] read digest in analysis cycle
```

### Storage

```
data/crypto/news/
  items.jsonl          # one JSON object per line (ingested + analyzed)
  latest_digest.json   # last cycle summary for API/UI/attach
  state.json           # last fetch times per feed, seen url hashes (trimmed)
```

### Default RSS sources (MVP)

Configurable in `settings.json` → `crypto_news.feeds[]`:

| id | name | url (example) |
|----|------|----------------|
| coindesk | CoinDesk | `https://www.coindesk.com/arc/outboundfeeds/rss/` |
| cointelegraph | Cointelegraph | `https://cointelegraph.com/rss` |
| fed | Federal Reserve | `https://www.federalreserve.gov/feeds/press_all.xml` |
| sec | SEC Press | `https://www.sec.gov/news/pressreleases.rss` |

Feeds may fail individually; pipeline continues and logs warnings.

### Rule scoring

- **Categories:** `macro`, `regulation`, `security`, `market`, `crypto_native`
- **Keyword tiers:** high (+30), medium (+15), low (+5) — configurable lists in code initially
- **Symbol boost:** title/summary mentions BTC/ETH/SOL → +10
- **Threshold:** default `min_score=40` for LLM candidacy
- **Top N for LLM:** default `llm_top_n=5` (env `CRYPTO_NEWS_LLM_TOP_N`)

Without `OPENAI_API_KEY`: emit rule-only `advice_template` (category + direction hint).

### LLM output schema (per item)

```json
{
  "headline": "string",
  "impact": "bullish|bearish|neutral|mixed",
  "confidence": 0.0,
  "affected_symbols": ["BTC", "ETH"],
  "horizon": "intraday|days|weeks",
  "advice": "1-3 sentences Chinese, 非下单指令",
  "risk_note": "uncertainty or counter-view"
}
```

Sync HTTP to OpenAI-compatible API (same pattern as `research.py`).

### Scheduling (S3)

**Independent news job**

- `ScheduleJobConfig.job_type = "news"`
- Fields: `interval_minutes` (default 120), `data_dir`, optional `feed_ids` filter
- Worker calls `run_news_cycle()` instead of `run_scheduled_cycle()`

**Attach to analysis cycle**

- `crypto_news.attach_to_analysis_cycle` (default `true`)
- After each successful symbol analysis batch, read `latest_digest.json` if fresh (< `digest_max_age_minutes`, default 180)
- Inject into report: `news_digest: { generated_at, top_items[], market_stance }`

### API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/crypto/news/digest` | Latest digest |
| GET | `/api/v1/crypto/news/items?limit=50` | Historical items |
| POST | `/api/v1/crypto/news/scan` | Manual one-shot scan |
| GET | `/api/v1/crypto/news/config` | Config + feed list |
| POST | `/api/v1/crypto/news/config` | Update thresholds/feeds flags |

### Frontend

- Route `/crypto-news` — **舆论雷达**: feed health, item timeline, impact badges, advice expand
- **AnalyzeView** / **CryptoOpsView** — card: overall stance + 2 headlines
- **SchedulesView** — create job type「舆论扫描」; link to config

### Alerts

`schedule_alerts.crypto_news`:

```json
{
  "on_high_impact": true,
  "min_score": 70,
  "min_llm_confidence": 0.8
}
```

Fires `_fire_alert` rule `news_high_impact` → Bark/Webhook. Cooldown uses existing per-job cooldown.

### Config (`settings.json` + `.env`)

**settings.json → `crypto_news`:**

```json
{
  "enabled": true,
  "min_score": 40,
  "llm_top_n": 5,
  "attach_to_analysis_cycle": true,
  "digest_max_age_minutes": 180,
  "feeds": []
}
```

**`.env` (optional overrides):**

- `CRYPTO_NEWS_LLM_TOP_N`
- `CRYPTO_NEWS_MIN_SCORE`
- Existing `OPENAI_API_KEY`, `CHAT_MODEL`

### Dependencies

- Add `feedparser>=6.0` to `pyproject.toml`

### Testing

- Fixture RSS XML → parse + normalize
- Scoring unit tests (keyword → score)
- Dedupe by URL
- Mock LLM → valid JSON merged into item
- Pipeline writes digest; attach reads stale vs fresh
- Scheduler `job_type=news` dispatches correct runner

### Disclaimer

All UI and LLM system prompts include: **仅供参考，不构成投资建议。**

## Error handling

- Per-feed fetch timeout 15s; failure does not abort cycle
- LLM failure: keep rule-only fields, log warning
- Missing digest on attach: skip silently

## Security

- Do not store API keys in `data/`; RSS URLs only in settings
- Sanitize HTML in titles (strip tags)
