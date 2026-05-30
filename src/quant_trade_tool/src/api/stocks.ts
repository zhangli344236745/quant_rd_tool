import { http } from "./http";

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

  screener: (body: {
    q?: string;
    has_report?: boolean | null;
    stance_in?: string[];
    watchlist_only?: boolean;
    codes?: string[];
    page?: number;
    page_size?: number;
  }) => http.post<{ total: number; items: Record<string, unknown>[] }>("/stocks/screener", body),
};
