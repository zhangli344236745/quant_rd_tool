import { http } from "./http";

export type JobType =
  | "qlib_analyze"
  | "analyze_stock"
  | "backtest_run"
  | "macro_panel"
  | "crypto_analyze"
  | "crypto_options_vol_scan"
  | "crypto_workflow"
  | "stock_workflow";

export interface JobRecord {
  id: string;
  type: JobType | string;
  code: string | null;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  message?: string;
  result_path?: string;
  error?: string;
  created_at: string;
  updated_at: string;
}

export const JOB_TYPE_LABELS: Record<string, string> = {
  qlib_analyze: "Qlib 分析",
  analyze_stock: "个股分析",
  backtest_run: "组合回测",
  macro_panel: "宏观面板",
  crypto_analyze: "Crypto 分析",
  crypto_options_vol_scan: "期权 IV 扫描",
  crypto_workflow: "Crypto Workflow",
  stock_workflow: "A股 Workflow",
};

export const jobsApi = {
  qlibAnalyze: (body: {
    code: string;
    years?: number;
    refresh?: boolean;
    with_ml?: boolean;
    ml_algorithm?: string;
  }) => http.post<{ job_id: string }>("/jobs/qlib-analyze", body),

  analyzeStock: (body: Record<string, unknown>) =>
    http.post<{ job_id: string }>("/jobs/analyze-stock", body),

  backtest: (body: Record<string, unknown>) =>
    http.post<{ job_id: string }>("/jobs/backtest", body),

  macroPanel: (body: Record<string, unknown>) =>
    http.post<{ job_id: string }>("/jobs/macro-panel", body),

  cryptoAnalyze: (body: Record<string, unknown>) =>
    http.post<{ job_id: string }>("/jobs/crypto-analyze", body),

  cryptoOptionsVolScan: (body?: { data_dir?: string; symbols?: string[]; lookback_days?: number }) =>
    http.post<{ job_id: string }>("/jobs/crypto-options-vol-scan", body ?? {}),

  cryptoWorkflow: (body: Record<string, unknown>) =>
    http.post<{ job_id: string }>("/jobs/crypto-workflow", body),

  stockWorkflow: (body: Record<string, unknown>) =>
    http.post<{ job_id: string }>("/jobs/stock-workflow", body),

  batchQlib: (body: { codes: string[]; years?: number; with_ml?: boolean }) =>
    http.post<{ job_ids: string[] }>("/jobs/batch-qlib", body),

  get: (id: string) => http.get<JobRecord>(`/jobs/${id}`),

  result: (id: string) => http.get<Record<string, unknown>>(`/jobs/${id}/result`),

  list: (params?: { status?: string; type?: string; limit?: number }) =>
    http.get<{ items: JobRecord[] }>("/jobs", { params }),

  cancel: (id: string) => http.post<JobRecord>(`/jobs/${id}/cancel`),

  retry: (id: string) => http.post<JobRecord>(`/jobs/${id}/retry`),

  screenerEnqueue: (body: {
    q?: string;
    has_report?: boolean | null;
    stance_in?: string[];
    watchlist_only?: boolean;
    codes?: string[];
    limit?: number;
    job_type?: "qlib_analyze" | "analyze_stock" | "stock_workflow";
    years?: number;
    max_attempts?: number;
    high_impact_only?: boolean;
    notice_keyword?: string;
    template_id?: string;
    workflow_steps?: Record<string, unknown>[];
    refresh?: boolean;
  }) =>
    http.post<{ job_ids: string[]; matched: number; enqueued: number }>(
      "/jobs/screener-enqueue",
      body,
    ),

  eventsUrl: (id: string) => {
    const base = http.defaults.baseURL || "/api/v1";
    const prefix = base ? base.replace(/\/$/, "") : `${window.location.origin}/api/v1`;
    return `${prefix}/jobs/${id}/events`;
  },
};
