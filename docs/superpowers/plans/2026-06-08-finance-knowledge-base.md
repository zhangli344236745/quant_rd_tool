# Finance Knowledge Base — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a finance knowledge base with project auto-ingest, user uploads, local vector search, and Local Cursor Agent hybrid Q&A in a new Web page.

**Architecture:** SQLite chunk store + OpenAI embeddings; `kb_ingest` scans project artifacts; `kb_cursor_agent` wraps cursor-sdk with customTools; FastAPI `/api/v1/kb/*` + `FinanceKnowledgeView.vue`.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, OpenAI embeddings, cursor-sdk, Vue 3 + Element Plus

**Spec:** [2026-06-08-finance-knowledge-base-design.md](../specs/2026-06-08-finance-knowledge-base-design.md)

---

## File map

| Action | Path |
|--------|------|
| Create | `src/quant_rd_tool/kb_store.py` |
| Create | `src/quant_rd_tool/kb_chunking.py` |
| Create | `src/quant_rd_tool/kb_embed.py` |
| Create | `src/quant_rd_tool/kb_search.py` |
| Create | `src/quant_rd_tool/kb_ingest.py` |
| Create | `src/quant_rd_tool/kb_cursor_agent.py` |
| Create | `src/quant_rd_tool/kb_chat.py` |
| Create | `src/quant_rd_tool/routes/knowledge.py` |
| Modify | `src/quant_rd_tool/config.py` |
| Modify | `src/quant_rd_tool/main.py` |
| Modify | `pyproject.toml` |
| Create | `src/quant_trade_tool/src/views/FinanceKnowledgeView.vue` |
| Create | `src/quant_trade_tool/src/api/knowledge.ts` |
| Modify | `src/quant_trade_tool/src/router/index.ts` |
| Modify | `src/quant_trade_tool/src/layouts/MainLayout.vue` |
| Create | `tests/test_kb_*.py` |

---

### Task 1: Config + store skeleton

**Files:** `config.py`, `kb_store.py`, `tests/test_kb_store.py`

- [ ] **Step 1:** Add settings fields `cursor_api_key`, `kb_cursor_model`, `kb_embedding_model`, `kb_data_dir="data/kb"`
- [ ] **Step 2:** Implement SQLite schema (documents, chunks, chat_sessions, messages)
- [ ] **Step 3:** Tests for init, insert doc/chunk, list, delete cascade
- [ ] **Step 4:** Commit

---

### Task 2: Chunking + embeddings

**Files:** `kb_chunking.py`, `kb_embed.py`, `tests/test_kb_chunking.py`

- [ ] **Step 1:** `split_text(text, chunk_size=512, overlap=64)` char-based MVP
- [ ] **Step 2:** `split_json_report(data)` by top-level keys
- [ ] **Step 3:** `embed_texts(texts) -> list[list[float]]` via OpenAI; mock in tests
- [ ] **Step 4:** `embed_texts_keyword_fallback` when no API key
- [ ] **Step 5:** Commit

---

### Task 3: Search

**Files:** `kb_search.py`, `tests/test_kb_search.py`

- [ ] **Step 1:** Cosine similarity over stored embeddings
- [ ] **Step 2:** `retrieve(query, top_k=8, tags=None) -> list[ChunkHit]`
- [ ] **Step 3:** Test with synthetic embeddings
- [ ] **Step 4:** Commit

---

### Task 4: Project ingest + upload

**Files:** `kb_ingest.py`, `tests/test_kb_ingest.py`

- [ ] **Step 1:** `content_hash(path|text)` for skip-if-unchanged
- [ ] **Step 2:** `scan_project(data_dir, docs_dir)` — stocks, crypto, news, specs
- [ ] **Step 3:** Export `tv_catalog` strategies as synthetic doc
- [ ] **Step 4:** `ingest_upload(file_bytes, filename, mime)`
- [ ] **Step 5:** PDF text extract via `pypdf` if available else skip with warning
- [ ] **Step 6:** Commit

---

### Task 5: Cursor agent layer

**Files:** `kb_cursor_agent.py`, `tests/test_kb_cursor_agent.py`

- [ ] **Step 1:** Add optional dep `cursor-sdk` in pyproject `[kb]`
- [ ] **Step 2:** Define customTools: `search_knowledge_base`, `get_crypto_analysis_summary`, `get_stock_report_summary`
- [ ] **Step 3:** `run_agent_chat(message, session_id?, context_chunks) -> AgentResult`
- [ ] **Step 4:** Session persist: create/resume agent_id in kb_store
- [ ] **Step 5:** Mock `Agent.create` in tests
- [ ] **Step 6:** Commit

---

### Task 6: Chat orchestration + API

**Files:** `kb_chat.py`, `routes/knowledge.py`, `main.py`, `tests/test_kb_routes.py`

- [ ] **Step 1:** `chat(message, session_id)` — retrieve → agent → map citations
- [ ] **Step 2:** SSE stream wrapper for `stream=true`
- [ ] **Step 3:** Routes: status, documents, upload, sync-project, chat, sessions
- [ ] **Step 4:** Register router in main.py
- [ ] **Step 5:** Route tests with mocked agent
- [ ] **Step 6:** Commit

---

### Task 7: Frontend

**Files:** `FinanceKnowledgeView.vue`, `api/knowledge.ts`, router, MainLayout

- [ ] **Step 1:** TS types + API client
- [ ] **Step 2:** Left doc panel + upload + sync button
- [ ] **Step 3:** Chat panel with streaming (fetch EventSource or chunked read)
- [ ] **Step 4:** Citation chips under assistant messages
- [ ] **Step 5:** Nav item「金融知识库」
- [ ] **Step 6:** Commit

---

### Task 8: Verification + README note

- [ ] Run `uv run pytest tests/test_kb_*.py -v`
- [ ] Manual: set `CURSOR_API_KEY`, sync project, ask「BTC 最新报告要点」
- [ ] README one-liner under new section
- [ ] Final commit

---

## Execution handoff

Plan complete. Choose:

1. **Subagent-Driven** — task-per-subagent with review  
2. **Inline Execution** — implement in this session with checkpoints

Which approach?
