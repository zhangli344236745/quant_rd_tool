# Finance Knowledge Base — Design Spec

**Status:** Approved — 2026-06-08  
**Scope:** 金融知识库：项目数据自动 ingest + 用户上传 + Local Cursor Agent hybrid 问答；独立 Web 聊天页

## User decisions (locked)

| Dimension | Choice |
|-----------|--------|
| 内容来源 | **C** — 项目数据自动同步 + 用户自定义文档 |
| Cursor 角色 | **Hybrid** — 本地 RAG Top-K + Agent customTools（search_kb、实时分析 API） |
| UI 入口 | **A** — 侧栏新页面「金融知识库」（聊天 + 文档管理 + 引用） |
| Agent 运行时 | **Local** — `LocalAgentOptions(cwd=project_root)`，可访问 `data/` |

## Goals

1. **知识沉淀**：自动索引 A 股/加密报告、新闻 digest、策略 spec、Zipline 策略元数据。
2. **用户扩展**：支持上传 MD/TXT/PDF，分块入库、可删除。
3. **智能问答**：基于 `CURSOR_API_KEY` 的 Local Cursor Agent，返回答案 + 可点击引用来源。
4. **实时补充**：Agent 可通过 customTools 调用 `search_knowledge_base`、现有 analyze/report API。

## Non-goals (MVP)

- Cloud Agent、多租户权限
- PDF OCR / 图片理解
- 定时自动 sync（Phase 2）
- Bark / Scheduler 联动
- 前端暴露 Cursor API Key

## Architecture

### High-level flow

```
FinanceKnowledgeView.vue
  → POST /api/v1/kb/chat { message, session_id?, stream? }
       → kb_search.retrieve_top_k(query)
       → kb_cursor_agent.run_local_agent(context + message, tools)
       → SSE stream or JSON { answer, citations[], session_id }
  → POST /api/v1/kb/sync-project
       → kb_ingest.scan_project(data/, docs/)
  → POST /api/v1/kb/upload
       → kb_ingest.ingest_file(uploads/)
```

### Module layout

| File | Responsibility |
|------|----------------|
| `kb_store.py` | SQLite meta + chunk storage; embedding blobs; CRUD documents |
| `kb_chunking.py` | Text split (512 tok / 64 overlap); JSON section split |
| `kb_embed.py` | OpenAI `text-embedding-3-small`; keyword fallback |
| `kb_search.py` | Vector cosine + optional BM25 hybrid retrieve |
| `kb_ingest.py` | Project scan + user upload pipeline |
| `kb_cursor_agent.py` | cursor-sdk Local Agent; customTools; session resume |
| `kb_chat.py` | Orchestrate retrieve → agent → citations |
| `routes/knowledge.py` | REST + SSE |
| `FinanceKnowledgeView.vue` | Chat UI, doc list, upload, sync |
| `api/knowledge.ts` | TypeScript client |

Extend:

| File | Change |
|------|--------|
| `config.py` | `cursor_api_key`, `kb_cursor_model`, `kb_embedding_model` |
| `MainLayout.vue` + `router/index.ts` | Nav + route `/finance-kb` |
| `main.py` | Register knowledge router |
| `pyproject.toml` | optional `kb = ["cursor-sdk>=..."]` |

### Storage layout

```
data/kb/
  meta.db                 # documents, chunks, chat_sessions, agent_ids
  uploads/                # user-uploaded originals
  sync_state.json         # last project sync fingerprints
```

**documents:** `id, title, source(project|upload), path, mime, tags_json, updated_at, chunk_count, content_hash`  
**chunks:** `id, doc_id, ord, text, embedding BLOB, meta_json`  
**chat_sessions:** `id, agent_id, title, created_at, updated_at`

### Auto-ingest sources (MVP)

| Source | Glob / API | Tags |
|--------|------------|------|
| A-share reports | `data/stocks/*/report.md`, `report.json` | `astock`, code |
| Crypto reports | `data/crypto/CRYPTO_*/report.md` | `crypto`, symbol |
| News digest | `data/crypto/news/digest*.json` | `news` |
| Design specs | `docs/superpowers/specs/*-design.md` | `docs`, `strategy` |
| TV strategies | `tv_catalog.list_tv_strategies()` export MD | `strategy`, `zipline` |

Incremental sync via content hash; unchanged files skipped.

### Cursor Agent integration

**Env:**

```env
CURSOR_API_KEY=...
KB_CURSOR_MODEL=composer-2.5
KB_EMBEDDING_MODEL=text-embedding-3-small
```

**Pattern:**

```python
# kb_cursor_agent.py — hybrid
chunks = kb_search.retrieve(query, top_k=8)
prompt = build_prompt(chunks, user_message)
with Agent.create(
    model=settings.kb_cursor_model,
    api_key=settings.cursor_api_key,
    local=LocalAgentOptions(cwd=project_root, custom_tools=[...]),
) as agent:
    run = agent.send(prompt)
    ...
```

**customTools (MVP):**

| Tool | Description |
|------|-------------|
| `search_knowledge_base` | Semantic search; params: `query`, `top_k`, `tags?` |
| `get_crypto_analysis_summary` | Latest crypto report summary for symbol |
| `get_stock_report_summary` | Latest A-share report via `report_index` |

Session: store `agent_id` in `chat_sessions`; follow-ups use `Agent.resume(agent_id)`.

**Fallback:** If `CURSOR_API_KEY` missing → `503` on `/kb/chat`; optional `KB_FALLBACK_OPENAI=true` uses existing OpenAI chat (config flag, off by default).

### API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/kb/status` | doc/chunk counts, last sync, cursor configured |
| GET | `/api/v1/kb/documents` | List docs; `?tag=&page=` |
| DELETE | `/api/v1/kb/documents/{id}` | Remove doc + chunks |
| POST | `/api/v1/kb/upload` | multipart file upload |
| POST | `/api/v1/kb/sync-project` | Trigger project ingest |
| POST | `/api/v1/kb/chat` | Chat; `stream: true` → SSE |
| GET | `/api/v1/kb/chat/sessions` | Session list |
| GET | `/api/v1/kb/chat/sessions/{id}` | History messages |

**Chat response:**

```json
{
  "session_id": "uuid",
  "answer": "markdown text",
  "citations": [
    {"doc_id": "...", "title": "BTC report", "chunk_id": "...", "snippet": "...", "path": "data/crypto/..."}
  ],
  "disclaimer": "仅供参考，不构成投资建议。"
}
```

### Frontend — FinanceKnowledgeView

Route: `/finance-kb`  
Side nav: **金融知识库**

Layout:

- **Left panel:** doc list, filters by tag, upload button,「同步项目数据」, delete
- **Right panel:** chat thread (streaming markdown), citation chips below each assistant message
- **Header:** status (N docs, last sync, Cursor ready/warn)

### Security

- `CURSOR_API_KEY` server-only in `.env`
- Upload: max 10MB; allow `.md`, `.txt`, `.pdf`
- No user-provided API keys in requests
- Disclaimer on every chat response

### Testing

| File | Coverage |
|------|----------|
| `test_kb_chunking.py` | Split boundaries, JSON sections |
| `test_kb_ingest.py` | Hash skip, project scan mock |
| `test_kb_search.py` | Retrieve with fake embeddings |
| `test_kb_routes.py` | API smoke; mock Cursor agent |
| `test_kb_cursor_agent.py` | Prompt build; mock Agent.create |

CI must not require live Cursor API.

### Dependencies

```toml
[project.optional-dependencies]
kb = ["cursor-sdk>=0.1.0"]
```

OpenAI embeddings reuse existing `OPENAI_API_KEY`.

### Risks

| Risk | Mitigation |
|------|------------|
| Cursor SDK not installed | optional extra `kb`; clear 503 message |
| Local Agent slow | SSE streaming; timeout 120s |
| Large `data/` sync slow | incremental hash; background job optional Phase 2 |
| Embedding cost | cache by content_hash; skip unchanged chunks |

## Approval

- [x] User approved design in chat (2026-06-08)
- [x] Implementation plan: `docs/superpowers/plans/2026-06-08-finance-knowledge-base.md`
