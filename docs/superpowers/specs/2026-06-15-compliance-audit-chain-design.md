# Compliance Audit Chain Design

**Status:** Approved 2026-06-15 (Milestone C)  
**Goal:** Tamper-evident research run records, report version locking, watermarked exports.

## Scope

1. **Audit chain** — append-only SHA256 hash chain for analyze / portfolio backtest / zipline lab runs
2. **Report integrity** — content hash on archive; optional version lock registry
3. **Watermarked export** — ZIP bundles include disclaimer header + compliance manifest

## Storage

- `data/stocks/compliance/audit_chain.jsonl` — run audit entries
- `data/stocks/compliance/report_locks.json` — locked report version ids per code
- Per-version `{vid}.meta.json` gains `content_hash`

## API

- `GET /stocks/compliance/audit` — tail audit chain
- `GET /stocks/compliance/audit/verify` — verify chain integrity
- `GET /stocks/compliance/audit/{run_id}` — single entry
- `POST /stocks/{code}/reports/{version_id}/lock` — lock archived version
- `GET /stocks/{code}/reports/{version_id}/verify` — verify report hash
- `GET /stocks/reports/export?watermark=1` — watermarked ZIP (default on)

## Out of scope (v1)

- External notarization / blockchain anchoring
- RBAC on lock operations
