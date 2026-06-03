import { http } from "./http";

export interface AnalyzeRequest {
  symbol: string;
  timeframe: string;
  limit: number;
  data_dir: string;
  with_ml: boolean;
  ml_algorithm: string;
  with_options_vol?: boolean;
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
      var?: Record<string, unknown>;
      webhook_on_alert?: boolean;
      on_cycle_complete?: boolean;
      bark?: {
        enabled?: boolean;
        device_key?: string;
        server?: string;
        device_key_from_env?: boolean;
        device_key_configured?: boolean;
      };
    }>("/crypto/schedules/alerts/rules"),

  scheduleAlertsTestBark: (body: {
    bark: { enabled?: boolean; device_key?: string; server?: string };
  }) => {
    const key = (body.bark.device_key || "").trim();
    const params = new URLSearchParams();
    if (key) params.set("device_key", key);
    const srv = body.bark.server?.trim();
    if (srv) params.set("server", srv);
    const qs = params.toString();
    return http.post<{ status: string; result?: Record<string, unknown> }>(
      qs ? `/crypto/schedules/alerts/test-bark?${qs}` : "/crypto/schedules/alerts/test-bark",
      { bark: body.bark },
    );
  },

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
    var?: Record<string, unknown>;
    bark?: { enabled?: boolean; device_key?: string; server?: string };
    webhook_on_alert?: boolean;
    on_cycle_complete?: boolean;
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

  perpOpenOrders: (params: { base: string; quote?: string; ccxt_symbol?: string; testnet?: boolean }) =>
    http.get<{ symbol: string; count: number; items: Record<string, unknown>[] }>("/crypto/perp/orders/open", {
      params,
    }),

  perpCancelOrder: (params: {
    base: string;
    order_id: string;
    quote?: string;
    ccxt_symbol?: string;
    testnet?: boolean;
  }) => http.post("/crypto/perp/orders/cancel", null, { params }),

  perpCancelAllOrders: (params: { base: string; quote?: string; ccxt_symbol?: string; testnet?: boolean }) =>
    http.post("/crypto/perp/orders/cancel-all", null, { params }),

  perpPosition: (params: { base: string; quote?: string; ccxt_symbol?: string; testnet?: boolean }) =>
    http.get<{
      enabled: boolean;
      symbol: string;
      position: null | {
        side: string;
        contracts: number;
        entry_price?: number | null;
        unrealized_pnl?: number | null;
      };
      error?: string;
    }>("/crypto/perp/position", { params }),

  perpAccountBalances: (params?: { testnet?: boolean }) =>
    http.get<{
      enabled: boolean;
      summary?: Record<string, unknown>;
      items: { asset: string; total: number; available?: number | null; used?: number | null }[];
      error?: string;
    }>("/crypto/perp/account/balances", { params }),

  perpAccountTrades: (params?: { base?: string; quote?: string; limit?: number; testnet?: boolean }) =>
    http.get<{
      enabled: boolean;
      symbol?: string;
      count?: number;
      items: Record<string, unknown>[];
      error?: string;
    }>("/crypto/perp/account/trades", { params }),

  perpAccountDailyPnl: (params?: { days?: number; testnet?: boolean }) =>
    http.get<{
      enabled: boolean;
      start?: string;
      end?: string;
      count?: number;
      items: { day: string; realizedPnl: number; funding: number; fees: number; net: number }[];
      error?: string;
    }>("/crypto/perp/account/daily-pnl", { params }),

  perpClosePosition: (params: { base: string; quote?: string; ccxt_symbol?: string; testnet?: boolean }) =>
    http.post("/crypto/perp/position/close", null, { params }),

  perpReconcileProtection: (params: {
    base: string;
    data_dir?: string;
    quote?: string;
    ccxt_symbol?: string;
    testnet?: boolean;
  }) => http.post("/crypto/perp/protection/reconcile", null, { params }),

  optionsVolScan: (params?: { symbols?: string; lookback_days?: number; persist?: boolean }) =>
    http.get<OptionsVolScanResult>("/crypto/options/volatility-scan", { params }),

  optionsVolConfig: () =>
    http.get<OptionsVolConfig>("/crypto/options/volatility-scan/config"),

  optionsVolConfigSave: (body: Partial<OptionsVolConfig>) =>
    http.post<OptionsVolConfig>("/crypto/options/volatility-scan/config", body),

  optionsVolHistory: (symbol: string, limit = 120) =>
    http.get<{ symbol: string; count: number; items: OptionsIvHistoryRow[] }>(
      "/crypto/options/volatility-scan/history",
      { params: { symbol, limit } },
    ),

  optionsStrikeProbability: (
    base: string,
    n = 5,
    expiry?: string,
    ctx?: { spot_stance?: string; iv_alert_level?: string; iv_percentile?: number },
  ) =>
    http.get<StrikeProbabilityReport>("/crypto/options/strike-probability", {
      params: { base, n, expiry, ...ctx },
    }),

  varSymbol: (params?: {
    symbol?: string;
    notional_usdt?: number;
    timeframe?: string;
    lookback_bars?: number;
    horizon_days?: number;
    confidence?: string;
    mc_n_sims?: number;
    mc_seed?: number;
  }) => http.get<SymbolVarReport>("/crypto/var/symbol", { params }),

  varPortfolio: (params?: {
    testnet?: boolean;
    timeframe?: string;
    lookback_bars?: number;
    horizon_days?: number;
    confidence?: string;
    mc_n_sims?: number;
    mc_seed?: number;
  }) => http.get<PortfolioVarReport>("/crypto/var/portfolio", { params }),

  varSymbolHistory: (params?: {
    symbol?: string;
    window?: number;
    confidence?: number;
    timeframe?: string;
    lookback_bars?: number;
    horizon_days?: number;
    notional_usdt?: number;
  }) => http.get<SymbolVarHistory>("/crypto/var/symbol/history", { params }),
};

export interface OptionsVolConfig {
  symbols: string[];
  lookback_days: number;
  iv_percentile_threshold: number;
  iv_change_24h_threshold: number;
  data_dir: string;
}

export interface OptionsVolItem {
  base: string;
  ts?: string;
  atm_iv?: number | null;
  iv_percentile?: number | null;
  iv_change_24h_pct?: number | null;
  alert_level?: string;
  alerts?: string[];
  rank?: number;
  composite_score?: number;
  cold_start?: boolean;
  contract?: string;
  expiry?: string;
  dte?: number;
  underlying_price?: number;
  strike?: number;
  error?: string;
}

export interface OptionsAdviceRow {
  base: string;
  stance: string;
  summary: string;
  actions: string[];
  risks: string[];
  reasons?: string[];
  confidence?: number;
}

export interface OptionsVolScanResult {
  scanned_at: string;
  config: OptionsVolConfig;
  items: OptionsVolItem[];
  advice_pack: {
    overview: string;
    disclaimer: string;
    advice: OptionsAdviceRow[];
  };
}

export interface OptionsIvHistoryRow {
  ts: string;
  atm_iv?: number;
  underlying_price?: number;
  contract?: string;
}

export interface StrikePurchaseAdvice {
  verdict?: string;
  summary?: string;
  reasons?: string[];
  strike?: number;
  symbol?: string;
}

export interface StrikeProbabilityRow {
  strike: number;
  side?: string;
  symbol?: string;
  moneyness_pct?: number;
  mark_iv?: number;
  model: {
    expiry_itm_call?: number | null;
    touch_call?: number | null;
  };
  implied: {
    expiry_itm_call?: number | null;
    touch_call?: number | null;
  };
  edge_expiry?: number | null;
  purchase?: StrikePurchaseAdvice;
}

export interface StrikePurchaseSummary {
  headline?: string;
  spot_stance?: string;
  iv_alert_level?: string;
  consider_count?: number;
  avoid_count?: number;
  best_strike?: number | null;
  best_contract?: string | null;
}

export interface VarBacktest {
  observations: number;
  violations: number;
  expected_violation_rate: number;
  actual_violation_rate: number;
  violation_ratio?: number | null;
  worst_day_return: number;
  max_exceedance_pct: number;
  backtest_ok?: boolean;
}

export interface MonteCarloVarLeg {
  var_pct: number;
  cvar_pct: number;
  var_usdt?: number;
  cvar_usdt?: number;
  df?: number;
  label?: string;
}

export interface MonteCarloVarBlock {
  n_simulations: number;
  seed: number;
  horizon_days: number;
  gbm: MonteCarloVarLeg;
  student_t: MonteCarloVarLeg;
}

export interface VarMetric {
  var_pct: number;
  cvar_pct: number;
  var_usdt: number;
  cvar_usdt: number;
  parametric_var_pct?: number | null;
  parametric_var_usdt?: number | null;
  method_spread_pct?: number | null;
  monte_carlo?: MonteCarloVarBlock | null;
  backtest?: VarBacktest;
}

export interface ReturnStats {
  mean_daily_return?: number;
  daily_volatility?: number;
  annualized_volatility?: number;
  skewness?: number | null;
  excess_kurtosis?: number | null;
  worst_day_return?: number;
  best_day_return?: number;
}

export interface ReturnHistogramBin {
  bin_low: number;
  bin_high: number;
  count: number;
}

export interface StressScenario {
  shock_pct: number;
  loss_pct: number;
  loss_usdt: number;
}

export interface VarNarrative {
  headline: string;
  bullets: string[];
  disclaimer: string;
}

export interface SymbolVarReport {
  symbol: string;
  method: string;
  params: {
    lookback_bars: number;
    horizon_days: number;
    confidence_levels: number[];
    timeframe: string;
  };
  notional_usdt: number;
  latest_price: number;
  observations: number;
  return_stats?: ReturnStats;
  return_histogram?: ReturnHistogramBin[];
  stress_scenarios?: StressScenario[];
  narrative?: VarNarrative;
  metrics: Record<string, VarMetric>;
}

export interface PortfolioVarPosition {
  base: string;
  side: string;
  symbol: string;
  contracts: number;
  notional_usdt: number;
  signed_notional_usdt: number;
  weight?: number;
  standalone_var_usdt?: number;
  var_contribution_usdt?: number;
  var_contribution_pct?: number;
}

export interface PortfolioVarReport {
  enabled: boolean;
  error?: string;
  message?: string;
  method?: string;
  params?: Record<string, unknown>;
  positions: PortfolioVarPosition[];
  gross_exposure_usdt?: number;
  net_exposure_usdt?: number;
  account_equity_usdt?: number | null;
  var_pct_of_equity?: number | null;
  diversification_ratio?: number | null;
  observations?: number;
  return_stats?: ReturnStats;
  correlation?: { symbols: string[]; matrix: (number | null)[][] };
  stress_scenarios?: StressScenario[];
  narrative?: VarNarrative;
  metrics: Record<string, VarMetric> | null;
}

export interface VarHistoryPoint {
  date: string;
  var_pct: number;
  var_usdt: number;
  actual_return?: number;
  breach?: boolean;
}

export interface SymbolVarHistory {
  symbol: string;
  confidence: number;
  window: number;
  lookback_bars: number;
  notional_usdt: number;
  breach_count?: number;
  series: VarHistoryPoint[];
}

export interface StrikeProbabilityReport {
  base: string;
  spot: number;
  expiry?: string;
  dte?: number;
  n: number;
  model: {
    enabled: boolean;
    sigma_ann?: number | null;
    mu_ann?: number;
    reason?: string;
    assumptions?: string;
    qlib?: Record<string, unknown>;
  };
  rows: StrikeProbabilityRow[];
  warnings: string[];
  disclaimer: string;
  purchase_summary?: StrikePurchaseSummary;
  purchase_disclaimer?: string;
}
