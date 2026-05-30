import { http } from "./http";

export interface AnalyzeRequest {
  symbol: string;
  timeframe: string;
  limit: number;
  data_dir: string;
  with_ml: boolean;
  ml_algorithm: string;
}

export interface PerpBotRequest {
  base: string;
  quote: string;
  timeframe: string;
  ohlcv_limit: number;
  leverage: number;
  usdt_risk_fraction: number;
  min_notional_usdt: number;
  max_daily_loss_pct: number;
  sl_pct: number;
  tp_pct: number;
  sizing_mode: string;
  atr_period: number;
  sl_atr: number;
  tp_atr: number;
  use_atr_sl_tp: boolean;
  max_protection_failures: number;
  dry_run: boolean;
  testnet: boolean;
  signal_only: boolean;
}

export interface PerpPortfolioRequest {
  symbols: string[];
  quote: string;
  timeframe: string;
  ohlcv_limit: number;
  leverage: number;
  usdt_risk_fraction: number;
  min_notional_usdt: number;
  total_notional_usdt: number;
  max_per_symbol_notional_usdt: number;
  max_concurrent_positions: number;
  dry_run: boolean;
  testnet: boolean;
  signal_only: boolean;
}

export interface ScheduleCreateRequest {
  symbols: string[];
  name: string;
  id: string;
  timeframe: string;
  interval_minutes: number;
  backfill_days: number;
  data_dir: string;
  with_ml: boolean;
  ml_algorithm: string;
  auto_start: boolean;
}

export const cryptoApi = {
  health: () => http.get("/health"),
  connectivity: (params: { exchange?: string; symbol?: string; timeframe?: string }) =>
    http.get("/crypto/connectivity", { params }),

  analyze: (body: AnalyzeRequest) => http.post("/crypto/analyze", body),

  spotBotRun: (body: Record<string, unknown>) => http.post("/crypto/bot/run", body),

  perpBotRun: (body: PerpBotRequest) => http.post("/crypto/perp-bot/run", body),

  perpPortfolioRun: (body: PerpPortfolioRequest) =>
    http.post("/crypto/perp-portfolio/run", body),

  scheduleRun: (body: Record<string, unknown>) => http.post("/crypto/schedule/run", body),

  schedulesList: (data_dir = "data/crypto") =>
    http.get("/crypto/schedules", { params: { data_dir } }),

  scheduleGet: (jobId: string, data_dir = "data/crypto") =>
    http.get(`/crypto/schedules/${jobId}`, { params: { data_dir } }),

  scheduleCreate: (body: ScheduleCreateRequest) => http.post("/crypto/schedules", body),

  scheduleStart: (jobId: string, data_dir = "data/crypto") =>
    http.post(`/crypto/schedules/${jobId}/start`, null, { params: { data_dir } }),

  scheduleStop: (jobId: string, data_dir = "data/crypto") =>
    http.post(`/crypto/schedules/${jobId}/stop`, null, { params: { data_dir } }),

  scheduleRunOnce: (jobId: string, data_dir = "data/crypto") =>
    http.post(`/crypto/schedules/${jobId}/run-once`, null, { params: { data_dir } }),

  scheduleDelete: (jobId: string, data_dir = "data/crypto") =>
    http.delete(`/crypto/schedules/${jobId}`, { params: { data_dir } }),

  scheduleAlertsRulesGet: () =>
    http.get<{
      enabled: boolean;
      on_cycle_error: boolean;
      on_worker_crash: boolean;
      consecutive_failures: number;
      stale_minutes: number;
      cooldown_minutes: number;
      custom_rules?: Record<string, unknown>[];
    }>("/crypto/schedules/alerts/rules"),

  scheduleAlertsRulesFormat: () =>
    http.get<{ doc?: string; example_rules: Record<string, unknown>[] }>(
      "/crypto/schedules/alerts/rules/format",
    ),

  scheduleAlertsRulesSave: (body: {
    enabled?: boolean;
    on_cycle_error?: boolean;
    on_worker_crash?: boolean;
    consecutive_failures?: number;
    stale_minutes?: number;
    cooldown_minutes?: number;
    custom_rules?: Record<string, unknown>[];
  }) => http.post("/crypto/schedules/alerts/rules", body),

  scheduleAlertsLog: (limit = 50) =>
    http.get<{ count: number; items: Record<string, unknown>[] }>("/crypto/schedules/alerts/log", {
      params: { limit },
    }),

  scheduleAlertsCheckStale: (data_dir = "data/crypto") =>
    http.post<{ fired: Record<string, unknown>[]; count: number }>(
      "/crypto/schedules/alerts/check-stale",
      null,
      { params: { data_dir } },
    ),

  opsControlGet: () =>
    http.get<{
      kill_switch: boolean;
      webhook_url: string;
      webhook_on_error: boolean;
      webhook_on_circuit_breaker: boolean;
      updated_at?: string;
    }>("/crypto/ops/control"),

  opsControlSave: (body: {
    kill_switch?: boolean;
    webhook_url?: string;
    webhook_on_error?: boolean;
    webhook_on_circuit_breaker?: boolean;
  }) => http.post("/crypto/ops/control", body),

  opsTestWebhook: () => http.post<{ status: string }>("/crypto/ops/control/test-webhook"),

  opsSummary: (params?: { data_dir?: string; log_dir?: string; telemetry_limit?: number }) =>
    http.get<{
      control?: {
        kill_switch: boolean;
        webhook_url: string;
        webhook_on_error: boolean;
        webhook_on_circuit_breaker: boolean;
      };
      schedules: { total: number; running: number; jobs: Record<string, unknown>[] };
      perp_states: Record<string, unknown>[];
      telemetry_days: string[];
      telemetry_summary: {
        total: number;
        decisions: Record<string, number>;
        error_count: number;
        circuit_breaker_blocks: number;
        last_ts?: string;
      };
      telemetry_recent: Record<string, unknown>[];
    }>("/crypto/ops/summary", { params }),

  perpTelemetry: (params?: { log_dir?: string; day?: string; limit?: number }) =>
    http.get<{
      items: Record<string, unknown>[];
      summary: Record<string, unknown>;
      available_days: string[];
    }>("/crypto/perp/telemetry", { params }),

  perpStates: (data_dir = "data/crypto") =>
    http.get<{ items: Record<string, unknown>[] }>("/crypto/perp/states", { params: { data_dir } }),
};
