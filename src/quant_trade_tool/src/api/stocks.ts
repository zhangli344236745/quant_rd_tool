import { getApiBase } from "@/config";
import { http } from "./http";

function _filenameFromDisposition(header: string | undefined, fallback: string): string {
  if (!header) return fallback;
  const m = /filename\*?=(?:UTF-8'')?"?([^";\n]+)"?/i.exec(header);
  return m?.[1]?.trim() || fallback;
}

function _triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export interface StockZiplineStrategy {
  id: string;
  name: string;
  description: string;
  default_params: Record<string, number>;
  min_bars: number;
  category?: string;
  source?: string;
  tv_ref?: string;
}

export interface StockZiplineTimeframeOption {
  id: string;
  label: string;
  bar_minutes: number;
}

export interface StockZiplineStatus {
  market?: string;
  timeframes?: StockZiplineTimeframeOption[];
  default_timeframe?: string;
  combo_modes?: string[];
  zipline_installed: boolean;
  zipline_inprocess?: boolean;
  zipline_venv?: boolean;
  zipline_venv_path?: string;
  default_engine?: string;
  zipline_error?: string | null;
  engines: string[];
  symbols: Array<{
    symbol: string;
    timeframe?: string;
    ready: boolean;
    bars_count: number;
    last_bar?: string;
  }>;
}

export interface StockZiplineSyncResult {
  synced: Record<string, unknown>[];
  errors: Array<{ symbol: string; error: string }>;
  timeframe: string;
}

export interface StockZiplineComboLeg {
  strategy: string;
  params?: Record<string, number>;
  weight?: number;
}

export interface StockZiplineBacktestRequest {
  symbol: string;
  strategy: string;
  start: string;
  end: string;
  capital_base?: number;
  strategy_params?: Record<string, number>;
  lookback_days?: number;
  sync_first?: boolean;
  engine?: "auto" | "pandas" | "zipline";
  force_reingest?: boolean;
  timeframe?: string;
  strategy_combo?: StockZiplineComboLeg[];
  combo_mode?: "vote" | "and" | "or" | "weighted";
}

export interface StockZiplineRunSummary {
  run_id: string;
  symbol?: string;
  strategy?: string;
  engine?: string;
  total_return?: number;
  generated_at?: string;
}

export interface StockZiplineBacktestResult {
  run_id: string;
  symbol: string;
  strategy: string;
  timeframe: string;
  engine: string;
  start: string;
  end: string;
  capital_base: number;
  metrics: {
    total_return: number;
    sharpe: number;
    max_drawdown: number;
    trade_count: number;
  };
  final_signal?: {
    position: string;
    target_pct: number;
    bar_time?: string;
  };
  trades?: Array<Record<string, unknown>>;
  equity_curve?: Array<{ time: string; value: number }>;
  disclaimer?: string;
  zipline_fallback_reason?: string;
  bundle?: string;
  bar_count?: number;
  ingest_skipped?: boolean;
  fingerprint?: string;
  generated_at?: string;
  ml_metrics?: {
    ic?: number;
    direction_accuracy?: number;
    train_samples?: number;
    feature_count?: number;
  };
  ml_preferred_engine?: boolean;
}

export interface StockVarBacktest {
  observations: number;
  violations: number;
  expected_violation_rate: number;
  actual_violation_rate: number;
  violation_ratio?: number | null;
  worst_day_return?: number;
  max_exceedance_pct?: number;
  backtest_ok?: boolean;
}

export interface StockMonteCarloVarLeg {
  var_pct: number;
  cvar_pct: number;
  var_cny?: number;
  cvar_cny?: number;
  df?: number;
  label?: string;
}

export interface StockMonteCarloVarBlock {
  n_simulations: number;
  seed: number;
  horizon_days: number;
  gbm: StockMonteCarloVarLeg;
  student_t: StockMonteCarloVarLeg;
}

export interface StockVarMetric {
  var_pct: number;
  cvar_pct: number;
  var_cny: number;
  cvar_cny: number;
  parametric_var_pct?: number | null;
  parametric_var_cny?: number | null;
  method_spread_pct?: number | null;
  monte_carlo?: StockMonteCarloVarBlock | null;
  backtest?: StockVarBacktest;
}

export interface StockVarNarrative {
  headline: string;
  bullets: string[];
  disclaimer: string;
}

export interface StockSymbolVarReport {
  market?: string;
  symbol: string;
  code?: string;
  method: string;
  params: {
    lookback_bars: number;
    horizon_days: number;
    confidence_levels: number[];
    timeframe: string;
    data_dir?: string;
    mc_n_sims?: number;
    mc_seed?: number;
  };
  notional_cny: number;
  latest_price: number;
  observations: number;
  return_stats?: {
    mean_daily_return?: number;
    daily_volatility?: number;
    annualized_volatility?: number;
    skewness?: number | null;
    excess_kurtosis?: number | null;
    worst_day_return?: number;
    best_day_return?: number;
  };
  return_histogram?: Array<{ bin_low: number; bin_high: number; count: number }>;
  stress_scenarios?: Array<{ shock_pct: number; loss_pct: number; loss_cny: number }>;
  narrative?: StockVarNarrative;
  metrics: Record<string, StockVarMetric>;
}

export interface StockPortfolioVarPosition {
  code: string;
  qlib_code: string;
  side: string;
  latest_price: number;
  shares?: number | null;
  notional_cny: number;
  signed_notional_cny: number;
  weight?: number;
  standalone_var_cny?: number;
  var_contribution_cny?: number;
  var_contribution_pct?: number;
}

export interface StockPortfolioVarReport {
  enabled: boolean;
  market?: string;
  error?: string;
  message?: string;
  method?: string;
  params?: Record<string, unknown>;
  positions: StockPortfolioVarPosition[];
  gross_exposure_cny?: number;
  net_exposure_cny?: number;
  diversification_ratio?: number | null;
  observations?: number;
  return_stats?: StockSymbolVarReport["return_stats"];
  correlation?: { symbols: string[]; matrix: (number | null)[][] };
  stress_scenarios?: Array<{ shock_pct: number; loss_pct: number; loss_cny: number }>;
  narrative?: StockVarNarrative;
  metrics: Record<string, StockVarMetric> | null;
}

export interface StockVarHistoryPoint {
  date: string;
  var_pct: number;
  var_cny: number;
  actual_return?: number;
  breach?: boolean;
}

export interface StockSymbolVarHistory {
  market?: string;
  symbol: string;
  code?: string;
  confidence: number;
  window: number;
  lookback_bars: number;
  notional_cny: number;
  breach_count: number;
  series: StockVarHistoryPoint[];
}

export interface StockVarHolding {
  symbol: string;
  notional_cny?: number;
  shares?: number;
}

export interface StockListItem {
  code: string;
  name: string;
  qlib_code: string;
}

export interface StockListResponse {
  total: number;
  page: number;
  page_size: number;
  items: StockListItem[];
}

export interface ProfileRow {
  key: string;
  value: unknown;
}

export interface QlibAnalyzeSummary {
  symbol?: string;
  period?: { start?: string; end?: string; bars?: number };
  stance?: string;
  summary?: string;
  observations?: string[];
  risks?: string[];
  disclaimer?: string;
  price?: Record<string, unknown>;
  returns?: Record<string, unknown>;
  technical?: Record<string, unknown>;
  risk?: Record<string, unknown>;
  benchmark?: Record<string, unknown>;
  ml?: Record<string, { signal?: string; predicted_return?: number }>;
  ml_skipped?: boolean;
  ml_skip_reason?: string;
}

export interface QlibAnalyzeResponse {
  code: string;
  qlib_code?: string;
  start_date: string;
  end_date: string;
  years: number;
  summary: QlibAnalyzeSummary;
  markdown?: string;
  report?: unknown;
}

export interface StockProfile {
  code: string;
  qlib_code: string;
  name: string;
  em: ProfileRow[];
  cninfo: ProfileRow[];
  errors?: Record<string, string>;
}

export const stocksApi = {
  list: (params: { q?: string; page?: number; page_size?: number }) =>
    http.get<StockListResponse>("/stocks/list", { params }),

  profile: (code: string) => http.get<StockProfile>(`/stocks/${code}/profile`),

  management: (code: string) =>
    http.get<{ code: string; count: number; items: Record<string, unknown>[] }>(
      `/stocks/${code}/management`,
    ),

  news: (code: string, limit = 30) =>
    http.get<{ code: string; count: number; items: Record<string, unknown>[] }>(
      `/stocks/${code}/news`,
      { params: { limit } },
    ),

  notices: (code: string, category = "全部", limit = 30) =>
    http.get<{ code: string; count: number; items: Record<string, unknown>[] }>(
      `/stocks/${code}/notices`,
      { params: { category, limit } },
    ),

  qlibAnalyze: (
    code: string,
    body?: {
      years?: number;
      refresh?: boolean;
      with_ml?: boolean;
      ml_algorithm?: string;
      include_full_report?: boolean;
    },
  ) => http.post<{ job_id: string }>(`/stocks/qlib-analyze/${code}`, body ?? {}),

  qlibAnalyzeSync: (
    code: string,
    body?: {
      years?: number;
      refresh?: boolean;
      with_ml?: boolean;
      ml_algorithm?: string;
      include_full_report?: boolean;
    },
  ) =>
    http.post<QlibAnalyzeResponse>(`/stocks/qlib-analyze/${code}`, body ?? {}, {
      params: { sync: true },
      timeout: 600_000,
    }),

  watchlist: () => http.get<{ items: { code: string; name: string; added_at?: string }[] }>("/stocks/watchlist"),

  addWatchlist: (code: string, name = "") =>
    http.post<{ item: { code: string; name: string } }>("/stocks/watchlist", { code, name }),

  removeWatchlist: (code: string) => http.delete<{ removed: boolean }>(`/stocks/watchlist/${code}`),

  reportsList: (params?: { q?: string; page?: number; page_size?: number }) =>
    http.get<{
      total: number;
      page: number;
      page_size: number;
      items: {
        code: string;
        qlib_code: string;
        stance?: string;
        summary?: string;
        report_mtime?: string;
      }[];
    }>("/stocks/reports", { params }),

  reportsLatest: (code: string) =>
    http.get<{
      code: string;
      qlib_code: string;
      stance?: string;
      summary?: string;
      markdown?: string;
      report_mtime?: string;
      macro?: { summary?: string; china?: Record<string, unknown>; global?: unknown[] };
      technical?: Record<string, unknown>;
      ml?: Record<string, unknown> | null;
      compliance?: {
        run_id?: string;
        entry_hash?: string;
        content_hash?: string;
        integrity?: { valid?: boolean; locked?: boolean };
      };
    }>(`/stocks/${code}/reports/latest`),

  reportsCompare: (codeA: string, codeB: string) =>
    http.get<{ a: Record<string, unknown>; b: Record<string, unknown> }>("/stocks/reports/compare", {
      params: { code_a: codeA, code_b: codeB },
    }),

  reportsExportUrl: (codes?: string) => {
    const base = http.defaults.baseURL || "/api/v1";
    const q = codes ? `?codes=${encodeURIComponent(codes)}` : "";
    return `${base}/stocks/reports/export${q}`;
  },

  reportsHistory: (code: string) =>
    http.get<{
      code: string;
      items: {
        version_id: string;
        stance?: string;
        summary?: string;
        report_mtime?: string;
        is_latest?: boolean;
        locked?: boolean;
        content_hash?: string;
      }[];
    }>(`/stocks/${code}/reports/history`),

  reportsDiff: (code: string, params?: { base_version?: string; compare_version?: string }) =>
    http.get<{
      summary: string;
      changes: { field: string; from: unknown; to: unknown }[];
      base_version: string;
      compare_version: string;
      base_stance?: string;
      compare_stance?: string;
    }>(`/stocks/${code}/reports/diff`, { params }),

  reportsLock: (code: string, versionId: string, body?: { locked_by?: string; reason?: string }) =>
    http.post<{ locked: Record<string, unknown> }>(`/stocks/${code}/reports/${versionId}/lock`, body ?? {}),

  reportsVerify: (code: string, versionId: string) =>
    http.get<{ valid: boolean; content_hash?: string; locked?: boolean; message?: string }>(
      `/stocks/${code}/reports/${versionId}/verify`,
    ),

  complianceAudit: (params?: { limit?: number; run_type?: string; code?: string }) =>
    http.get<{ items: Record<string, unknown>[]; count: number }>("/stocks/compliance/audit", { params }),

  complianceAuditVerify: () =>
    http.get<{ valid: boolean; entries: number; errors?: string[] }>("/stocks/compliance/audit/verify"),

  complianceAuditGet: (runId: string) =>
    http.get<Record<string, unknown>>(`/stocks/compliance/audit/${runId}`),

  oosProtocol: (
    code: string,
    params?: { algorithm?: "xgb" | "lgb" | "both"; start_date?: string; end_date?: string; data_dir?: string },
  ) =>
    http.get<{
      code: string;
      qlib_code: string;
      oos_protocol?: Record<string, unknown>;
      oos_summary?: {
        gate_passed?: boolean;
        test_ic?: number;
        direction_accuracy?: number;
        markdown?: string;
      };
      skipped?: boolean;
      reason?: string;
    }>(`/stocks/${code}/oos-protocol`, { params }),

  screener: (body: {
    q?: string;
    has_report?: boolean | null;
    stance_in?: string[];
    watchlist_only?: boolean;
    codes?: string[];
    high_impact_only?: boolean;
    notice_keyword?: string;
    page?: number;
    page_size?: number;
  }) => http.post<{ total: number; items: Record<string, unknown>[] }>("/stocks/screener", body),

  ziplineStatus: (data_dir = "data/stocks", symbols?: string, timeframe?: string) =>
    http.get<StockZiplineStatus>("/stocks/zipline/status", {
      params: { data_dir, symbols, timeframe },
    }),

  ziplineStrategies: () =>
    http.get<{ strategies: StockZiplineStrategy[] }>("/stocks/zipline/strategies"),

  ziplineSetupVenv: () =>
    http.post<{ ok: boolean; python?: string; error?: string | null }>("/stocks/zipline/setup-venv"),

  ziplineSync: (body: { symbols: string[]; data_dir?: string; backfill_days?: number }) =>
    http.post<StockZiplineSyncResult>("/stocks/zipline/sync", {
      data_dir: body.data_dir ?? "data/stocks",
      symbols: body.symbols,
      backfill_days: body.backfill_days ?? 800,
    }),

  ziplineExportDownload: async (params: {
    symbol: string;
    timeframe?: string;
    start?: string;
    end?: string;
    format?: "csv" | "zip";
    run_id?: string;
    data_dir?: string;
    lookback_days?: number;
  }) => {
    const format = params.format ?? "csv";
    const res = await http.get("/stocks/zipline/data/export", {
      params: {
        symbol: params.symbol,
        data_dir: params.data_dir ?? "data/stocks",
        timeframe: params.timeframe ?? "1d",
        format,
        start: params.start,
        end: params.end,
        run_id: params.run_id,
        lookback_days: params.lookback_days ?? 800,
      },
      responseType: "blob",
    });
    const blob = res.data as Blob;
    if (blob.type?.includes("json")) {
      const text = await blob.text();
      let msg = text;
      try {
        const err = JSON.parse(text) as { detail?: string };
        if (typeof err.detail === "string") msg = err.detail;
      } catch {
        /* keep raw text */
      }
      throw new Error(msg);
    }
    const fallback = `${params.symbol}_${params.timeframe ?? "1d"}.${format}`;
    const filename = _filenameFromDisposition(
      res.headers["content-disposition"] as string | undefined,
      fallback,
    );
    _triggerBlobDownload(blob, filename);
  },

  ziplineBacktest: (body: StockZiplineBacktestRequest) =>
    http.post<StockZiplineBacktestResult>("/stocks/zipline/backtest", {
      data_dir: "data/stocks",
      lookback_days: 800,
      timeframe: "1d",
      ...body,
    }),

  ziplineRuns: (data_dir = "data/stocks", limit = 20) =>
    http.get<{ count: number; runs: StockZiplineRunSummary[] }>("/stocks/zipline/runs", {
      params: { data_dir, limit },
    }),

  ziplineRun: (run_id: string, data_dir = "data/stocks") =>
    http.get<StockZiplineBacktestResult>("/stocks/zipline/runs/" + run_id, { params: { data_dir } }),

  varSymbol: (params?: {
    symbol?: string;
    notional_cny?: number;
    data_dir?: string;
    lookback_bars?: number;
    horizon_days?: number;
    confidence?: string;
    mc_n_sims?: number;
    mc_seed?: number;
  }) =>
    http.get<StockSymbolVarReport>("/stocks/var/symbol", {
      params: { data_dir: "data/stocks", ...params },
    }),

  varSymbolHistory: (params?: {
    symbol?: string;
    window?: number;
    confidence?: number;
    data_dir?: string;
    lookback_bars?: number;
    horizon_days?: number;
    notional_cny?: number;
  }) =>
    http.get<StockSymbolVarHistory>("/stocks/var/symbol/history", {
      params: { data_dir: "data/stocks", ...params },
    }),

  varPortfolio: (body: {
    holdings: StockVarHolding[];
    data_dir?: string;
    lookback_bars?: number;
    horizon_days?: number;
    confidence?: string;
    mc_n_sims?: number;
    mc_seed?: number;
  }) =>
    http.post<StockPortfolioVarReport>("/stocks/var/portfolio", {
      data_dir: "data/stocks",
      lookback_bars: 252,
      horizon_days: 1,
      confidence: "0.95,0.99",
      ...body,
    }),

  varPortfolioGet: (params?: {
    symbols?: string;
    notionals?: string;
    data_dir?: string;
    lookback_bars?: number;
    horizon_days?: number;
    confidence?: string;
    mc_n_sims?: number;
    mc_seed?: number;
  }) =>
    http.get<StockPortfolioVarReport>("/stocks/var/portfolio", {
      params: { data_dir: "data/stocks", ...params },
    }),

  listRefresh: () => http.post<{ count: number; refreshed_at: string }>("/stocks/list/refresh"),

  schedulesList: (data_dir = "data/stocks") =>
    http.get<{ count: number; jobs: Record<string, unknown>[] }>("/stocks/schedules", {
      params: { data_dir },
    }),

  scheduleGet: (jobId: string, data_dir = "data/stocks") =>
    http.get(`/stocks/schedules/${jobId}`, { params: { data_dir } }),

  scheduleCreate: (body: {
    symbols?: string[];
    name?: string;
    id?: string;
    interval_minutes?: number;
    years?: number;
    data_dir?: string;
    with_ml?: boolean;
    ml_algorithm?: string;
    with_openbb?: boolean;
    use_watchlist?: boolean;
    job_type?: "stock_qlib" | "stock_watchlist" | "stock_announcements" | "";
    auto_start?: boolean;
  }) => http.post("/stocks/schedules", body),

  scheduleStart: (jobId: string, data_dir = "data/stocks") =>
    http.post(`/stocks/schedules/${jobId}/start`, null, { params: { data_dir } }),

  scheduleStop: (jobId: string, data_dir = "data/stocks") =>
    http.post(`/stocks/schedules/${jobId}/stop`, null, { params: { data_dir } }),

  scheduleRunOnce: (jobId: string, data_dir = "data/stocks") =>
    http.post(`/stocks/schedules/${jobId}/run-once`, null, { params: { data_dir } }),

  scheduleDelete: (jobId: string, data_dir = "data/stocks") =>
    http.delete(`/stocks/schedules/${jobId}`, { params: { data_dir } }),

  workflowSteps: () => http.get<{ steps: StockWorkflowStepDef[] }>("/stocks/workflow/steps"),

  workflowTemplates: (data_dir = "data/stocks") =>
    http.get<{ count: number; templates: StockWorkflowTemplate[] }>("/stocks/workflow/templates", {
      params: { data_dir },
    }),

  workflowTemplateSave: (body: StockWorkflowTemplate, data_dir = "data/stocks") =>
    body.id
      ? http.put<{ ok: boolean; template: StockWorkflowTemplate }>(
          `/stocks/workflow/templates/${body.id}`,
          body,
          { params: { data_dir } },
        )
      : http.post<{ ok: boolean; template: StockWorkflowTemplate }>("/stocks/workflow/templates", body, {
          params: { data_dir },
        }),

  workflowTemplateDuplicate: (templateId: string, data_dir = "data/stocks", name?: string) =>
    http.post<{ ok: boolean; template: StockWorkflowTemplate }>(
      `/stocks/workflow/templates/${templateId}/duplicate`,
      null,
      { params: { data_dir, name } },
    ),

  workflowRun: (body: Record<string, unknown>) =>
    http.post<StockWorkflowRunResult>("/stocks/workflow/run", {
      data_dir: "data/stocks",
      refresh_ohlcv: true,
      ...body,
    }),

  workflowRuns: (data_dir = "data/stocks", limit = 20) =>
    http.get<{ count: number; runs: StockWorkflowRunSummary[] }>("/stocks/workflow/runs", {
      params: { data_dir, limit },
    }),

  workflowRunGet: (run_id: string, data_dir = "data/stocks") =>
    http.get<StockWorkflowRunResult>(`/stocks/workflow/runs/${run_id}`, { params: { data_dir } }),

  announcementsDigest: (data_dir = "data/stocks") =>
    http.get<{ digest: StockAnnouncementDigest }>("/stocks/announcements/digest", { params: { data_dir } }),

  announcementsItems: (params?: { data_dir?: string; limit?: number }) =>
    http.get<{ count: number; items: StockAnnouncementItem[] }>("/stocks/announcements/items", {
      params: { data_dir: params?.data_dir ?? "data/stocks", limit: params?.limit ?? 50 },
    }),

  announcementsScan: (body?: {
    symbols?: string[];
    use_watchlist?: boolean;
    notice_limit?: number;
    min_score?: number;
  }) =>
    http.post<StockAnnouncementScanResult>("/stocks/announcements/scan", {
      use_watchlist: true,
      notice_limit: 15,
      min_score: 40,
      ...body,
    }),

  opsSummary: (params?: { data_dir?: string; stale_calendar_days?: number }) =>
    http.get<StockOpsSummary>("/stocks/ops/summary", { params }),

  opsConnectivity: (params?: { data_dir?: string; probe_code?: string }) =>
    http.get<StockConnectivityProbe>("/stocks/ops/connectivity", { params }),
};

export interface StockWorkflowStepDef {
  id: string;
  name: string;
  description: string;
  params_schema?: Record<string, unknown>;
  required?: boolean;
}

export interface StockWorkflowStepConfig {
  id: string;
  enabled: boolean;
  order: number;
  params: Record<string, unknown>;
}

export interface StockWorkflowTemplate {
  id?: string;
  name: string;
  symbol_default?: string;
  timeframe?: string;
  data_dir?: string;
  steps: StockWorkflowStepConfig[];
}

export interface StockWorkflowStepResult {
  id: string;
  status: string;
  summary?: string;
  error?: string;
  elapsed_s?: number;
  output?: Record<string, unknown>;
}

export interface StockWorkflowAdvice {
  headline?: string;
  stance?: string;
  advice?: string;
  bullets?: string[];
  markdown?: string;
  disclaimer?: string;
  suggested_position_pct?: number;
  risk_level?: string;
  confidence?: number;
  signal_agreement?: string;
  var_gate_triggered?: boolean;
  price_guidance?: Record<string, unknown> & { available?: boolean };
}

export interface StockWorkflowRunResult {
  run_id: string;
  symbol: string;
  code?: string;
  timeframe: string;
  template_id?: string;
  template_name?: string;
  bars?: number;
  steps: StockWorkflowStepResult[];
  advice?: StockWorkflowAdvice | null;
  audit_record?: {
    run_id?: string;
    entry_hash?: string;
    content_hash?: string;
  };
  generated_at?: string;
  generated_at_beijing?: string;
}

export interface StockWorkflowRunSummary {
  run_id: string;
  symbol?: string;
  code?: string;
  stance?: string;
  risk_level?: string;
  generated_at?: string;
}

export interface StockAnnouncementItem {
  ts?: string;
  code?: string;
  title?: string;
  published?: string;
  score?: number;
  keywords?: string[];
  source?: string;
  category?: string;
}

export interface StockAnnouncementDigest {
  generated_at?: string;
  symbols_scanned?: number;
  items_new?: number;
  top_items?: StockAnnouncementItem[];
  errors?: Array<{ code?: string; error?: string }>;
}

export interface StockAnnouncementScanResult {
  items_processed?: number;
  items_new?: number;
  symbols?: string[];
  digest?: StockAnnouncementDigest;
  fetch_errors?: Array<{ code?: string; error?: string }>;
  error?: string;
}

export interface StockConnectivityProbe {
  ok: boolean;
  probe_code?: string;
  source?: string;
  bars?: number;
  latency_ms?: number;
  error?: string;
}

export interface StockDataFreshnessItem {
  code?: string;
  symbol?: string;
  ready?: boolean;
  bars_count?: number;
  last_bar?: string;
  days_old?: number | null;
  stale?: boolean;
}

export interface StockOpsSummary {
  market?: string;
  data_dir?: string;
  connectivity: StockConnectivityProbe;
  data_freshness: {
    symbols_checked?: number;
    stale_count?: number;
    stale_calendar_days?: number;
    checked_at?: string;
    items?: StockDataFreshnessItem[];
  };
  announcements: {
    digest_generated_at?: string;
    items_new?: number;
    symbols_scanned?: number;
    top_items?: StockAnnouncementItem[];
    errors?: Array<{ code?: string; error?: string }>;
  };
  schedules: {
    total?: number;
    running?: number;
    jobs?: Record<string, unknown>[];
  };
  schedule_alerts?: Record<string, unknown>;
  schedule_alert_recent?: Record<string, unknown>[];
  schedule_stale_checks?: Record<string, unknown>[];
}
