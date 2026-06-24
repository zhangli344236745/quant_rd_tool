# Polymarket Arbitrage v1.1 — Optimization Design

**Approved:** 2026-06-23  
**Base spec:** `2026-06-23-polymarket-arb-design.md`

## Phases

| Phase | Focus |
|-------|--------|
| A | UX alignment with Carry (preview, live status, filters, events) |
| B | Scan performance (concurrent books, Gamma cache, timing metrics) |
| C | Data insights (stats, scan history, volume column) |

## Phase A — API

- `GET /polymarket/preview?condition_id=&size_shares=`
- `GET /polymarket/positions/{id}/close-preview`
- `GET /polymarket/positions` enriches open rows with `live_status`

## Phase B — Performance

- `ThreadPoolExecutor(max_workers=10)` for per-market book scans
- In-memory Gamma cache TTL 60s
- Scan payload adds `duration_sec`, `books_fetched`, `books_failed`

## Phase C — Analytics

- `GET /polymarket/stats` — today scans, hit rate, avg/best edge, PnL
- `GET /polymarket/scans/history?limit=20` — recent scan summaries

## Non-goals

Live trading, WebSocket books, cross-venue arb (unchanged from v1).
