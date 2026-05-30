# A 股专业投研工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the A-share company module into a professional workbench: async analyze/qlib jobs, report library, watchlist, batch queue, and frontend tabs/drawer—without multi-tenant auth (C positioning).

**Architecture:** SQLite job store + single-thread worker dequeue; job handlers call existing `analyze_stock` and `run_qlib_stock_analysis`. Report index scans `data/stocks/{qlib_code}/`. Watchlist is JSON on disk. FastAPI routes under `/api/v1/jobs` and extended `/api/v1/stocks`. Vue adds watchlist filter, job drawer, and detail「分析」tab.

**Tech Stack:** Python 3.11–3.12, FastAPI, uvicorn, SQLite (stdlib), Vue 3, Element Plus, axios, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-astock-professional-workbench-design.md`

---

## File Structure (lock-in)

**Create**
- `src/quant_rd_tool/job_store.py` — SQLite CRUD + status transitions
- `src/quant_rd_tool/job_runner.py` — background worker thread + handler registry
- `src/quant_rd_tool/report_index.py` — scan/list/read report summaries
- `src/quant_rd_tool/watchlist.py` — watchlist JSON CRUD
- `src/quant_rd_tool/network_settings.py` — load/apply proxy from `data/settings.json`
- `src/quant_rd_tool/routes/jobs.py` — Job HTTP API
- `src/quant_trade_tool/src/api/jobs.ts` — frontend job client
- `src/quant_trade_tool/src/components/JobDrawer.vue` — global task drawer
- `tests/test_job_store.py`
- `tests/test_report_index.py`
- `tests/test_watchlist.py`
- `tests/test_job_runner.py`
- `tests/test_routes_jobs.py`

**Modify**
- `src/quant_rd_tool/routes/__init__.py` — include `jobs.router`
- `src/quant_rd_tool/routes/stocks.py` — watchlist, reports, async qlib default
- `src/quant_rd_tool/main.py` — startup: init job DB + start worker; shutdown hook
- `src/quant_rd_tool/akshare_stocks.py` — optional proxy hint in errors
- `src/quant_trade_tool/src/api/stocks.ts` — watchlist, reports, job-based qlib
- `src/quant_trade_tool/src/views/AStockListView.vue` — watchlist tab, batch, job submit
- `src/quant_trade_tool/src/views/AStockDetailView.vue` — 分析 tab
- `src/quant_trade_tool/src/layouts/MainLayout.vue` — JobDrawer + badge
- `src/quant_trade_tool/src/views/SettingsView.vue` — proxy + export/import
- `README.md` — jobs API, proxy troubleshooting

---

### Task 1: Job store (SQLite)

**Files:**
- Create: `src/quant_rd_tool/job_store.py`
- Test: `tests/test_job_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_job_store.py
import pytest
from quant_rd_tool.job_store import JobStore

@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "jobs.db")

def test_create_and_get(store):
    j = store.create(type="qlib_analyze", code="600519", payload={"years": 2})
    got = store.get(j["id"])
    assert got["status"] == "queued"
    assert got["code"] == "600519"

def test_transition_running_done(store):
    j = store.create(type="qlib_analyze", code="600519", payload={})
    store.mark_running(j["id"], message="fetch")
    store.mark_done(j["id"], result_path="data/stocks/SH600519/report.json", message="ok")
    got = store.get(j["id"])
    assert got["status"] == "done"
    assert got["progress"] == 1.0

def test_list_filter_status(store):
    store.create(type="qlib_analyze", code="1", payload={})
    j2 = store.create(type="qlib_analyze", code="2", payload={})
    store.mark_failed(j2["id"], error="boom")
    rows = store.list_jobs(status="failed")
    assert len(rows) == 1
    assert rows[0]["code"] == "2"
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/test_job_store.py -v`  
Expected: `ModuleNotFoundError` or missing `JobStore`

- [ ] **Step 3: Implement `JobStore`**

Requirements:
- Schema: table `jobs` per spec (`id` UUID text PK, `type`, `code`, `payload` JSON text, `status`, `progress` REAL default 0, `message`, `result_path`, `error`, `created_at`, `updated_at`)
- Methods: `create`, `get`, `list_jobs(status=, type=, limit=)`, `mark_running`, `mark_progress`, `mark_done`, `mark_failed`, `mark_cancelled`, `claim_next_queued` (atomic UPDATE … RETURNING for single worker)
- On `JobStore(db_path)` create parent dirs + `CREATE TABLE IF NOT EXISTS`
- `mark_cancelled` only if current status is `queued`

- [ ] **Step 4: Run test — expect PASS**

Run: `uv run pytest tests/test_job_store.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/job_store.py tests/test_job_store.py
git commit -m "feat: add SQLite job store for async stock analysis"
```

---

### Task 2: Report index

**Files:**
- Create: `src/quant_rd_tool/report_index.py`
- Test: `tests/test_report_index.py`

- [ ] **Step 1: Write failing tests**

Use `tmp_path` layout:

```
data/stocks/SH600519/report.json  {"symbol":"SH600519","narrative":{"stance":"偏多","summary":"test"}}
data/stocks/SH600519/report.md
```

```python
def test_list_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data" / "stocks" / "SH600519"
    root.mkdir(parents=True)
    (root / "report.json").write_text(
        '{"symbol":"SH600519","narrative":{"stance":"偏多","summary":"s"}}',
        encoding="utf-8",
    )
    (root / "report.md").write_text("# hi", encoding="utf-8")
    from quant_rd_tool.report_index import list_reports, latest_report
    items = list_reports(data_dir="data/stocks")
    assert len(items) == 1
    assert items[0]["qlib_code"] == "SH600519"
    assert items[0]["stance"] == "偏多"
    latest = latest_report("600519", data_dir="data/stocks")
    assert latest["summary"] == "s"
    assert "markdown" in latest
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/test_report_index.py -v`

- [ ] **Step 3: Implement `report_index`**

- `list_reports(data_dir, q=, page=, page_size=)` — iterate subdirs with `report.json`, sort by mtime desc
- `latest_report(code, data_dir)` — use `stock_storage.stock_root` + read `report.json`, optional `report.md` body (cap 64KB)
- `report_history(code, data_dir)` — Phase 1: return `[latest]` only if single file; if multiple `report.json.bak.*` not used yet—list by mtime of `report.json` + `meta.json` `job_id` if present
- Map `code` → qlib via `akshare_data.to_qlib_code`

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/quant_rd_tool/report_index.py tests/test_report_index.py
git commit -m "feat: add report index scanner for local stock reports"
```

---

### Task 3: Watchlist

**Files:**
- Create: `src/quant_rd_tool/watchlist.py`
- Test: `tests/test_watchlist.py`

- [ ] **Step 1: Write failing tests**

```python
def test_add_remove_list(tmp_path):
    from quant_rd_tool.watchlist import Watchlist
    wl = Watchlist(tmp_path / "watchlist.json")
    wl.add("600519", name="贵州茅台")
    assert wl.list_codes() == ["600519"]
    wl.remove("600519")
    assert wl.list_codes() == []
```

- [ ] **Step 2–4: Implement + pass**

- Default path: `data/stocks/watchlist.json`
- `add(code, name?)`, `remove`, `list_items()` → `[{code, name, added_at}]`
- Dedupe on add; resolve name from cached list if omitted (optional call `list_a_stocks`—keep sync file-only in v1)

- [ ] **Step 5: Commit**

---

### Task 4: Job runner + handlers

**Files:**
- Create: `src/quant_rd_tool/job_runner.py`
- Create: `src/quant_rd_tool/network_settings.py`
- Test: `tests/test_job_runner.py`

- [ ] **Step 1: Write failing test (mock heavy work)**

```python
def test_runner_executes_qlib_job(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    from quant_rd_tool.job_store import JobStore
    from quant_rd_tool.job_runner import JobRunner

    store = JobStore(db)
    j = store.create(type="qlib_analyze", code="600519", payload={"years": 1, "with_ml": False})

    def fake_run(code, **kw):
        root = tmp_path / "data" / "stocks" / "SH600519"
        root.mkdir(parents=True)
        (root / "report.json").write_text('{"symbol":"SH600519"}', encoding="utf-8")
        return {"code": code, "summary": {}}

    monkeypatch.setattr("quant_rd_tool.job_runner.astk.run_qlib_stock_analysis", fake_run)
    runner = JobRunner(store, data_dir=str(tmp_path / "data" / "stocks"))
    runner.run_once()
    got = store.get(j["id"])
    assert got["status"] == "done"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `JobRunner`**

- `handlers`: `analyze_stock` → `stock_analysis.analyze_stock`; `qlib_analyze` → `akshare_stocks.run_qlib_stock_analysis`; `batch_qlib` → create child jobs (store parent id in payload) OR sequential codes in one job with progress steps (spec: parent+children—create children in POST handler, runner only runs leaf types)
- `run_once()`: `claim_next_queued` → `mark_running` → apply `network_settings.apply()` → handler → `mark_done` with `result_path` from return value
- Thread: `start_background(interval=0.5)` / `stop()` using `threading.Event` (mirror `scheduler_manager` style)
- On exception: `mark_failed`
- `network_settings.py`: read `data/settings.json` keys `http_proxy`, `https_proxy`, `no_proxy`; set `os.environ` in runner only

- [ ] **Step 4: Pass tests**

Run: `uv run pytest tests/test_job_runner.py -v`

- [ ] **Step 5: Commit**

---

### Task 5: Jobs API + app lifecycle

**Files:**
- Create: `src/quant_rd_tool/routes/jobs.py`
- Modify: `src/quant_rd_tool/routes/__init__.py`, `src/quant_rd_tool/main.py`
- Test: `tests/test_routes_jobs.py`

- [ ] **Step 1: Write API test with TestClient**

```python
from fastapi.testclient import TestClient
from unittest.mock import patch

def test_enqueue_qlib_returns_job_id():
    from quant_rd_tool.main import app
    client = TestClient(app)
    with patch("quant_rd_tool.job_runner.JobRunner.run_once"):
        r = client.post("/api/v1/jobs/qlib-analyze", json={"code": "600519", "years": 2, "with_ml": False})
    assert r.status_code == 202
    assert "job_id" in r.json()
```

Note: May need `app.state.job_runner` initialized in test fixture or lifespan.

- [ ] **Step 2: Implement routes**

`routes/jobs.py`:
- `POST /qlib-analyze` body: `{code, years?, refresh?, with_ml?, ml_algorithm?, data_dir?}` → create job → **202** `{job_id}`
- `POST /analyze-stock` body: fields from `AnalyzeRequest` → job type `analyze_stock`
- `POST /batch-qlib` body: `{codes: string[], ...}` → create parent job + N child jobs queued
- `GET /{job_id}`, `GET /` list, `POST /{job_id}/cancel`

`main.py` lifespan or `@app.on_event("startup")`:
```python
store = JobStore(Path("data/jobs/jobs.db"))
runner = JobRunner(store)
runner.start_background()
app.state.job_store = store
app.state.job_runner = runner
```

- [ ] **Step 3: Wire `routes/__init__.py`**

`api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])`

- [ ] **Step 4: Adjust `stocks.py` qlib endpoint**

`POST /qlib-analyze/{code}`:
- Default: create job via `job_store`, return 202 + `{job_id}`
- Query `sync=1`: call `_qlib_analyze_handler` directly (current behavior)

- [ ] **Step 5: Add stocks routes**

- `GET /watchlist`, `POST /watchlist`, `DELETE /watchlist/{code}`
- `GET /reports`, `GET /{code}/reports/latest`, `GET /{code}/reports/history`

- [ ] **Step 6: Run tests**

`uv run pytest tests/test_routes_jobs.py tests/test_job_store.py -v`

- [ ] **Step 7: Commit**

---

### Task 6: Frontend — jobs API + drawer

**Files:**
- Create: `src/quant_trade_tool/src/api/jobs.ts`
- Create: `src/quant_trade_tool/src/components/JobDrawer.vue`
- Modify: `src/quant_trade_tool/src/layouts/MainLayout.vue`, `src/quant_trade_tool/src/api/stocks.ts`

- [ ] **Step 1: `jobs.ts`**

```typescript
export const jobsApi = {
  qlibAnalyze: (body: { code: string; years?: number; with_ml?: boolean }) =>
    http.post<{ job_id: string }>("/jobs/qlib-analyze", body),
  get: (id: string) => http.get<JobRecord>(`/jobs/${id}`),
  list: (params?: { status?: string; limit?: number }) =>
    http.get<{ items: JobRecord[] }>("/jobs", { params }),
  cancel: (id: string) => http.post(`/jobs/${id}/cancel`),
};
```

- [ ] **Step 2: `JobDrawer.vue`**

- Poll every 2s while any job `queued|running`
- Table: type, code, status tag, progress, message, actions (cancel / 查看报告)
- Emit `open-report` with code when done

- [ ] **Step 3: `MainLayout`**

- Header button with `ElBadge` (active count)
- `<JobDrawer v-model="drawerOpen" />`

- [ ] **Step 4: Update `stocks.ts`**

- `watchlist.list/add/remove`
- `reports.list`, `reports.latest(code)`
- Change `qlibAnalyze` to POST `/jobs/qlib-analyze` with `{code, ...}` OR keep path and handle 202 in dialog

- [ ] **Step 5: Build**

`cd src/quant_trade_tool && npm run build`

- [ ] **Step 6: Commit** (frontend + api)

---

### Task 7: Frontend — list + detail workbench

**Files:**
- Modify: `AStockListView.vue`, `AStockDetailView.vue`, `QlibAnalyzeDialog.vue`

- [ ] **Step 1: List view**

- `ElRadioGroup`: 全部 / 自选 (`GET watchlist`)
- Star icon toggle watchlist per row
- Multi-select + 「批量 Qlib」→ `POST /jobs/batch-qlib` → open drawer
- Qlib dialog: on submit → job id toast + drawer (remove 10min blocking wait)

- [ ] **Step 2: Detail view — Tab「分析」**

- On mount/tab: `stocksApi.reports.latest(code)`
- Show `SignalSummary` or stance/summary cards
- `ElButton`: 重新 Qlib / 完整 analyze (job)
- `ElScrollbar` with markdown preview (`marked` or plain `<pre>` if no dep)
- Link to open job drawer on pending

- [ ] **Step 3: Manual QA checklist**

1. 自选添加 600519  
2. 提交 Qlib job → drawer 显示 running → done  
3. 详情分析 Tab 显示 report  
4. 批量 2 只股票入队  

- [ ] **Step 4: Commit**

---

### Task 8: Settings proxy + README (M5)

**Files:**
- Modify: `SettingsView.vue`, `network_settings.py`, `README.md`

- [ ] **Step 1: Settings UI**

- Fields: HTTP proxy, HTTPS proxy, No proxy
- Save → `POST /api/v1/settings/network` (add minimal route in `routes/meta.py` or new `routes/settings.py`) OR write via existing pattern—**prefer** `POST /api/v1/meta/settings` saving `data/settings.json`

- [ ] **Step 2: Export/import**

- Export: download JSON `{watchlist, settings}`
- Import: file upload restore

- [ ] **Step 3: README section**

「macOS 系统代理 / ProxyError」+ jobs API table + `serve --reload`

- [ ] **Step 4: Full test suite**

Run: `uv run pytest -q`  
Expected: all pass (112+ tests)

- [ ] **Step 5: Commit**

---

## Execution Handoff

**Plan saved to:** `docs/superpowers/plans/2026-05-29-astock-professional-workbench.md`

**Two execution options:**

1. **Subagent-Driven (recommended)** — one fresh subagent per task (Tasks 1–8), review between tasks. Use @superpowers:subagent-driven-development.

2. **Inline Execution** — run Tasks 1→8 in this session with checkpoints after M2 and M4. Use @superpowers:executing-plans.

Which approach do you want?
