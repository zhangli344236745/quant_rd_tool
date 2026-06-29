<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  cryptoApi,
  type PortfolioVarBreach,
  type PortfolioVarReport,
  type ReturnHistogramBin,
  type SymbolVarBreach,
  type SymbolVarHistory,
  type SymbolVarReport,
  type VarMetric,
} from "@/api/crypto";
import { extractError } from "@/api/http";

const route = useRoute();
const router = useRouter();

const activeTab = ref<"symbol" | "portfolio">("symbol");

const symbolForm = ref({
  symbol: "BTC",
  notional_usdt: 10000,
  timeframe: "1d" as "1d" | "4h" | "1h",
  lookback_bars: 0,
  horizon_days: 1,
  horizon_bars: 1,
  conf90: false,
  conf95: true,
  conf99: true,
  mc_n_sims: 10000,
});

const defaultLookback = (tf: string) => ({ "1d": 252, "4h": 360, "1h": 720 }[tf] ?? 252);
const defaultRollingWindow = (tf: string) => ({ "1d": 60, "4h": 90, "1h": 168 }[tf] ?? 60);

const symbolLoading = ref(false);
const symbolError = ref("");
const symbolReport = ref<SymbolVarReport | null>(null);

const historyLoading = ref(false);
const symbolHistory = ref<SymbolVarHistory | null>(null);
const symbolBreach = ref<SymbolVarBreach | null>(null);

const portfolioLoading = ref(false);
const portfolioError = ref("");
const portfolioReport = ref<PortfolioVarReport | null>(null);
const portfolioBreach = ref<PortfolioVarBreach | null>(null);

function varParams() {
  const tf = symbolForm.value.timeframe;
  const lb = symbolForm.value.lookback_bars > 0 ? symbolForm.value.lookback_bars : defaultLookback(tf);
  return {
    timeframe: tf,
    lookback_bars: lb,
    horizon_days: symbolForm.value.horizon_days,
    horizon_bars: symbolForm.value.horizon_bars,
    confidence: confidenceParam(),
    mc_n_sims: symbolForm.value.mc_n_sims,
  };
}

function primaryConfidence() {
  return symbolForm.value.conf99 ? 0.99 : symbolForm.value.conf95 ? 0.95 : 0.9;
}

function rollingWindowLabel() {
  const tf = symbolForm.value.timeframe;
  const win = symbolHistory.value?.window ?? defaultRollingWindow(tf);
  return `滚动 VaR（近 ${win} 根 ${tf} K 线）`;
}

function confidenceParam(): string {
  const levels: string[] = [];
  if (symbolForm.value.conf90) levels.push("0.90");
  if (symbolForm.value.conf95) levels.push("0.95");
  if (symbolForm.value.conf99) levels.push("0.99");
  return levels.length ? levels.join(",") : "0.95,0.99";
}

function pct(v: number | undefined | null) {
  if (v == null) return "—";
  return (v * 100).toFixed(2) + "%";
}

function usdt(v: number | undefined | null) {
  if (v == null) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function confLabel(key: string) {
  const n = parseFloat(key);
  if (!Number.isFinite(n)) return key;
  return `${Math.round(n * 100)}%`;
}

const symbolMetricKeys = computed(() =>
  symbolReport.value ? Object.keys(symbolReport.value.metrics).sort() : [],
);

const portfolioMetricKeys = computed(() =>
  portfolioReport.value?.metrics ? Object.keys(portfolioReport.value.metrics).sort() : [],
);

function metricAt(metrics: Record<string, VarMetric> | null | undefined, key: string): VarMetric | undefined {
  return metrics?.[key];
}

const histMax = computed(() => {
  const bins = symbolReport.value?.return_histogram || [];
  return Math.max(1, ...bins.map((b) => b.count));
});

const rollingMaxVar = computed(() => {
  const s = symbolHistory.value?.series || [];
  return Math.max(1e-9, ...s.map((x) => x.var_pct));
});

function syncFromRoute() {
  const tab = String(route.query.tab || "");
  if (tab === "portfolio" || tab === "symbol") activeTab.value = tab;
  const sym = String(route.query.symbol || "").toUpperCase();
  if (["BTC", "ETH", "SOL", "BNB"].includes(sym)) symbolForm.value.symbol = sym;
}

function pushRouteQuery() {
  router.replace({
    query: {
      tab: activeTab.value,
      symbol: symbolForm.value.symbol,
    },
  });
}

async function loadSymbolVar() {
  if (!symbolForm.value.conf90 && !symbolForm.value.conf95 && !symbolForm.value.conf99) {
    ElMessage.warning("请至少选择一个置信水平");
    return;
  }
  symbolLoading.value = true;
  symbolError.value = "";
  symbolReport.value = null;
  symbolHistory.value = null;
  symbolBreach.value = null;
  pushRouteQuery();
  try {
    const p = varParams();
    const { data } = await cryptoApi.varSymbol({
      symbol: symbolForm.value.symbol,
      notional_usdt: symbolForm.value.notional_usdt,
      ...p,
    });
    symbolReport.value = data;
    await Promise.all([loadSymbolHistory(), loadSymbolBreach()]);
  } catch (e) {
    symbolError.value = extractError(e);
    ElMessage.error(symbolError.value);
  } finally {
    symbolLoading.value = false;
  }
}

async function loadSymbolHistory() {
  const tf = symbolForm.value.timeframe;
  const lb = symbolForm.value.lookback_bars > 0 ? symbolForm.value.lookback_bars : defaultLookback(tf);
  historyLoading.value = true;
  try {
    const { data } = await cryptoApi.varSymbolHistory({
      symbol: symbolForm.value.symbol,
      window: defaultRollingWindow(tf),
      confidence: primaryConfidence(),
      lookback_bars: lb,
      horizon_days: symbolForm.value.horizon_days,
      horizon_bars: symbolForm.value.horizon_bars,
      notional_usdt: symbolForm.value.notional_usdt,
      timeframe: tf,
    });
    symbolHistory.value = data;
  } catch {
    symbolHistory.value = null;
  } finally {
    historyLoading.value = false;
  }
}

async function loadSymbolBreach() {
  const tf = symbolForm.value.timeframe;
  const lb = symbolForm.value.lookback_bars > 0 ? symbolForm.value.lookback_bars : defaultLookback(tf);
  try {
    const { data } = await cryptoApi.varSymbolBreach({
      symbol: symbolForm.value.symbol,
      confidence: primaryConfidence(),
      timeframe: tf,
      lookback_bars: lb,
      horizon_days: symbolForm.value.horizon_days,
      horizon_bars: symbolForm.value.horizon_bars,
      notional_usdt: symbolForm.value.notional_usdt,
    });
    symbolBreach.value = data;
  } catch {
    symbolBreach.value = null;
  }
}

async function loadPortfolioVar() {
  portfolioLoading.value = true;
  portfolioError.value = "";
  portfolioReport.value = null;
  portfolioBreach.value = null;
  pushRouteQuery();
  try {
    const p = varParams();
    const { data } = await cryptoApi.varPortfolio({
      testnet: false,
      ...p,
    });
    portfolioReport.value = data;
    try {
      const breachRes = await cryptoApi.varPortfolioBreach({
        testnet: false,
        confidence: primaryConfidence(),
        timeframe: p.timeframe,
        lookback_bars: p.lookback_bars,
        horizon_days: p.horizon_days,
        horizon_bars: p.horizon_bars,
      });
      portfolioBreach.value = breachRes.data;
    } catch {
      portfolioBreach.value = null;
    }
  } catch (e) {
    portfolioError.value = extractError(e);
    ElMessage.error(portfolioError.value);
  } finally {
    portfolioLoading.value = false;
  }
}

function histBarStyle(bin: ReturnHistogramBin) {
  const h = Math.round((bin.count / histMax.value) * 100);
  return { height: `${Math.max(4, h)}%` };
}

function rollingBarStyle(varPct: number) {
  const h = Math.round((varPct / rollingMaxVar.value) * 100);
  return { height: `${Math.max(6, h)}%` };
}

watch(activeTab, () => pushRouteQuery());

watch(
  () => route.query,
  () => syncFromRoute(),
);

onMounted(() => {
  syncFromRoute();
  if (activeTab.value === "portfolio") loadPortfolioVar();
});
</script>

<template>
  <div>
    <h1 class="page-title">风险 VaR</h1>
    <p class="page-desc">
      历史模拟 + 参数法 + 蒙特卡洛对照；支持 1d / 4h / 1h 周期、bar 级持有期、滚动 VaR 突破检测与调度告警。
    </p>

    <el-card shadow="never" class="panel-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="单标的" name="symbol">
          <el-form label-width="120px" size="small" class="symbol-form">
            <el-row :gutter="16">
              <el-col :span="6">
                <el-form-item label="标的">
                  <el-select v-model="symbolForm.symbol" style="width: 100%">
                    <el-option label="BTC" value="BTC" />
                    <el-option label="ETH" value="ETH" />
                    <el-option label="SOL" value="SOL" />
                    <el-option label="BNB" value="BNB" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="K 线周期">
                  <el-select v-model="symbolForm.timeframe" style="width: 100%">
                    <el-option label="日线 1d" value="1d" />
                    <el-option label="4 小时 4h" value="4h" />
                    <el-option label="1 小时 1h" value="1h" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="名义 (USDT)">
                  <el-input-number v-model="symbolForm.notional_usdt" :min="0" :step="1000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="回看 K 线">
                  <el-input-number
                    v-model="symbolForm.lookback_bars"
                    :min="0"
                    :max="2000"
                    :placeholder="String(defaultLookback(symbolForm.timeframe))"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="持有期 (bar)">
                  <el-input-number v-model="symbolForm.horizon_bars" :min="1" :max="96" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="6">
                <el-form-item label="持有期 (天)">
                  <el-input-number v-model="symbolForm.horizon_days" :min="1" :max="30" style="width: 100%" />
                  <div class="muted small">未设 bar 时生效</div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="置信水平">
                  <el-checkbox v-model="symbolForm.conf90">90%</el-checkbox>
                  <el-checkbox v-model="symbolForm.conf95">95%</el-checkbox>
                  <el-checkbox v-model="symbolForm.conf99">99%</el-checkbox>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="MC 路径数">
                  <el-input-number v-model="symbolForm.mc_n_sims" :min="1000" :max="100000" :step="1000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label=" ">
                  <el-button type="primary" :loading="symbolLoading" @click="loadSymbolVar">计算 VaR</el-button>
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>

          <el-alert v-if="symbolError" type="error" :title="symbolError" show-icon class="mb" />

          <template v-if="symbolReport">
            <el-alert
              v-if="symbolBreach?.breached"
              type="error"
              :title="`最新 ${symbolBreach.timeframe} K 线突破 VaR：实际 ${pct(symbolBreach.actual_return)}，VaR ${pct(symbolBreach.var_pct)}`"
              show-icon
              :closable="false"
              class="mb"
            />

            <el-alert
              v-if="symbolReport.narrative?.headline"
              type="info"
              :title="symbolReport.narrative.headline"
              :closable="false"
              class="mb"
            >
              <ul v-if="symbolReport.narrative.bullets?.length" class="narrative-list">
                <li v-for="(b, i) in symbolReport.narrative.bullets" :key="i">{{ b }}</li>
              </ul>
              <p class="muted small mt">{{ symbolReport.narrative.disclaimer }}</p>
            </el-alert>

            <p class="muted small mb">
              {{ symbolReport.symbol }} · {{ symbolReport.params?.timeframe }} · 现货
              {{ symbolReport.latest_price }} · 名义 {{ usdt(symbolReport.notional_usdt) }} USDT · 样本
              {{ symbolReport.observations }} 期
              <span v-if="symbolReport.params?.effective_horizon_days != null">
                · 有效持有 {{ symbolReport.params.effective_horizon_days }} 天
              </span>
              <span v-if="symbolReport.return_stats?.annualized_volatility != null">
                · 年化波动 {{ pct(symbolReport.return_stats.annualized_volatility) }}
              </span>
            </p>

            <el-row :gutter="12">
              <el-col v-for="key in symbolMetricKeys" :key="key" :span="12">
                <el-card shadow="never" class="stat-card">
                  <div class="stat-label">{{ symbolForm.horizon_days }} 日 {{ confLabel(key) }} 风险</div>
                  <div class="stat-val warn">VaR {{ usdt(metricAt(symbolReport.metrics, key)?.var_usdt) }} USDT</div>
                  <div class="stat-sub">
                    历史 {{ pct(metricAt(symbolReport.metrics, key)?.var_pct) }} · 参数
                    {{ pct(metricAt(symbolReport.metrics, key)?.parametric_var_pct) }} · CVaR
                    {{ usdt(metricAt(symbolReport.metrics, key)?.cvar_usdt) }} USDT
                  </div>
                  <div v-if="metricAt(symbolReport.metrics, key)?.monte_carlo" class="stat-sub mc-line">
                    MC·GBM {{ usdt(metricAt(symbolReport.metrics, key)?.monte_carlo?.gbm.var_usdt) }}
                    ({{ pct(metricAt(symbolReport.metrics, key)?.monte_carlo?.gbm.var_pct) }})
                    · t(df={{ metricAt(symbolReport.metrics, key)?.monte_carlo?.student_t.df }})
                    {{ usdt(metricAt(symbolReport.metrics, key)?.monte_carlo?.student_t.var_usdt) }}
                    ({{ pct(metricAt(symbolReport.metrics, key)?.monte_carlo?.student_t.var_pct) }})
                  </div>
                  <div
                    v-if="metricAt(symbolReport.metrics, key)?.backtest"
                    class="stat-sub"
                    :class="{ 'text-ok': metricAt(symbolReport.metrics, key)?.backtest?.backtest_ok }"
                  >
                    回测违规 {{ metricAt(symbolReport.metrics, key)?.backtest?.violations }} /
                    {{ metricAt(symbolReport.metrics, key)?.backtest?.observations }}
                    ({{ pct(metricAt(symbolReport.metrics, key)?.backtest?.actual_violation_rate) }})
                  </div>
                </el-card>
              </el-col>
            </el-row>

            <el-card
              v-if="symbolMetricKeys.length && metricAt(symbolReport.metrics, symbolMetricKeys[0])?.monte_carlo"
              shadow="never"
              class="panel-card mt inner-card"
            >
              <template #header>VaR 方法对照（{{ symbolMetricKeys.map(confLabel).join(" / ") }}）</template>
              <el-table :data="symbolMetricKeys.map((k) => ({ conf: confLabel(k), key: k }))" size="small" stripe>
                <el-table-column prop="conf" label="置信" width="64" />
                <el-table-column label="历史" width="88">
                  <template #default="{ row }">{{ pct(metricAt(symbolReport.metrics, row.key)?.var_pct) }}</template>
                </el-table-column>
                <el-table-column label="参数" width="88">
                  <template #default="{ row }">{{ pct(metricAt(symbolReport.metrics, row.key)?.parametric_var_pct) }}</template>
                </el-table-column>
                <el-table-column label="MC·GBM" width="88">
                  <template #default="{ row }">
                    {{ pct(metricAt(symbolReport.metrics, row.key)?.monte_carlo?.gbm.var_pct) }}
                  </template>
                </el-table-column>
                <el-table-column label="MC·t" width="88">
                  <template #default="{ row }">
                    {{ pct(metricAt(symbolReport.metrics, row.key)?.monte_carlo?.student_t.var_pct) }}
                  </template>
                </el-table-column>
                <el-table-column label="t 自由度" width="80">
                  <template #default="{ row }">
                    {{ metricAt(symbolReport.metrics, row.key)?.monte_carlo?.student_t.df ?? "—" }}
                  </template>
                </el-table-column>
              </el-table>
              <p class="muted small mt">
                模拟路径 {{ metricAt(symbolReport.metrics, symbolMetricKeys[0])?.monte_carlo?.n_simulations?.toLocaleString() }}
                条 · seed {{ metricAt(symbolReport.metrics, symbolMetricKeys[0])?.monte_carlo?.seed }}
              </p>
            </el-card>

            <el-row :gutter="16" class="mt">
              <el-col :span="12">
                <el-card shadow="never" class="inner-card">
                  <template #header>日收益分布</template>
                  <div v-if="symbolReport.return_histogram?.length" class="hist-chart">
                    <div
                      v-for="(bin, i) in symbolReport.return_histogram"
                      :key="i"
                      class="hist-bar-wrap"
                      :title="`${pct(bin.bin_low)} ~ ${pct(bin.bin_high)}: ${bin.count}`"
                    >
                      <div class="hist-bar" :style="histBarStyle(bin)" />
                    </div>
                  </div>
                  <p v-else class="muted small">样本不足</p>
                  <el-descriptions v-if="symbolReport.return_stats" :column="2" size="small" border class="mt">
                    <el-descriptions-item label="最差日">{{ pct(symbolReport.return_stats.worst_day_return) }}</el-descriptions-item>
                    <el-descriptions-item label="最佳日">{{ pct(symbolReport.return_stats.best_day_return) }}</el-descriptions-item>
                    <el-descriptions-item label="偏度">{{ symbolReport.return_stats.skewness ?? "—" }}</el-descriptions-item>
                    <el-descriptions-item label="超额峰度">{{ symbolReport.return_stats.excess_kurtosis ?? "—" }}</el-descriptions-item>
                  </el-descriptions>
                </el-card>
              </el-col>
              <el-col :span="12">
                <el-card shadow="never" class="inner-card">
                  <template #header>压力情景（固定冲击）</template>
                  <el-table :data="symbolReport.stress_scenarios || []" size="small" stripe>
                    <el-table-column prop="shock_pct" label="冲击 %" width="88" />
                    <el-table-column label="损失 USDT">
                      <template #default="{ row }">{{ usdt(row.loss_usdt) }}</template>
                    </el-table-column>
                  </el-table>
                </el-card>
              </el-col>
            </el-row>

            <el-card v-loading="historyLoading" shadow="never" class="panel-card mt inner-card">
              <template #header>
                {{ rollingWindowLabel() }}
                <span v-if="symbolHistory?.breach_count != null" class="muted small">
                  · 窗口内突破 {{ symbolHistory.breach_count }} 次
                </span>
              </template>
              <div v-if="symbolHistory?.series?.length" class="rolling-chart">
                <div
                  v-for="(pt, i) in symbolHistory.series"
                  :key="i"
                  class="rolling-bar-wrap"
                  :class="{ breach: pt.breach }"
                  :title="`${pt.date}: VaR ${pct(pt.var_pct)}, 实际 ${pct(pt.actual_return)}`"
                >
                  <div class="rolling-bar" :style="rollingBarStyle(pt.var_pct)" />
                </div>
              </div>
              <el-table
                v-if="symbolHistory?.series?.length"
                :data="[...symbolHistory.series].reverse().slice(0, 15)"
                size="small"
                max-height="200"
                stripe
                class="mt"
              >
                <el-table-column prop="date" label="日期" min-width="120" show-overflow-tooltip />
                <el-table-column label="VaR %" width="80">
                  <template #default="{ row }">{{ pct(row.var_pct) }}</template>
                </el-table-column>
                <el-table-column label="实际收益" width="88">
                  <template #default="{ row }">{{ pct(row.actual_return) }}</template>
                </el-table-column>
                <el-table-column label="突破" width="64">
                  <template #default="{ row }">
                    <el-tag v-if="row.breach" type="danger" size="small">是</el-tag>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </template>
        </el-tab-pane>

        <el-tab-pane label="组合" name="portfolio">
          <p class="muted small mb">
            参数与「单标的」页共用（回看 / 持有期 / 置信度）。持仓来自 Binance 永续账户。
          </p>
          <div class="toolbar">
            <el-button type="primary" :loading="portfolioLoading" @click="loadPortfolioVar">
              加载组合 VaR
            </el-button>
          </div>

          <el-alert v-if="portfolioError" type="error" :title="portfolioError" show-icon class="mb mt" />

          <template v-if="portfolioReport">
            <el-alert
              v-if="!portfolioReport.enabled"
              type="warning"
              :title="portfolioReport.error || '未启用'"
              show-icon
              class="mb mt"
            />
            <el-alert
              v-else-if="portfolioReport.message"
              type="info"
              :title="portfolioReport.message"
              show-icon
              :closable="false"
              class="mb mt"
            />

            <template v-if="portfolioReport.enabled">
              <el-alert
                v-if="portfolioBreach?.breached"
                type="error"
                :title="`组合最新 ${portfolioBreach.timeframe} K 线突破 VaR：实际 ${pct(portfolioBreach.actual_return)}，VaR ${pct(portfolioBreach.var_pct)}`"
                show-icon
                :closable="false"
                class="mb mt"
              />

              <el-alert
                v-if="portfolioReport.narrative?.headline"
                type="info"
                :title="portfolioReport.narrative.headline"
                :closable="false"
                class="mb mt"
              >
                <ul v-if="portfolioReport.narrative.bullets?.length" class="narrative-list">
                  <li v-for="(b, i) in portfolioReport.narrative.bullets" :key="i">{{ b }}</li>
                </ul>
              </el-alert>

              <el-row v-if="portfolioReport.metrics" :gutter="12" class="mt">
                <el-col v-for="key in portfolioMetricKeys" :key="key" :span="12">
                  <el-card shadow="never" class="stat-card">
                    <div class="stat-label">组合 {{ confLabel(key) }} VaR</div>
                    <div class="stat-val warn">
                      {{ usdt(metricAt(portfolioReport.metrics, key)?.var_usdt) }} USDT
                    </div>
                    <div class="stat-sub">
                      历史 {{ pct(metricAt(portfolioReport.metrics, key)?.var_pct) }} · 参数
                      {{ pct(metricAt(portfolioReport.metrics, key)?.parametric_var_pct) }} · CVaR
                      {{ usdt(metricAt(portfolioReport.metrics, key)?.cvar_usdt) }} USDT
                    </div>
                    <div v-if="metricAt(portfolioReport.metrics, key)?.monte_carlo" class="stat-sub mc-line">
                      MC·GBM {{ pct(metricAt(portfolioReport.metrics, key)?.monte_carlo?.gbm.var_pct) }}
                      · MC·t {{ pct(metricAt(portfolioReport.metrics, key)?.monte_carlo?.student_t.var_pct) }}
                    </div>
                  </el-card>
                </el-col>
              </el-row>

              <p v-if="portfolioReport.gross_exposure_usdt != null" class="muted small mt">
                总敞口 {{ usdt(portfolioReport.gross_exposure_usdt) }} · 净敞口
                {{ usdt(portfolioReport.net_exposure_usdt) }} USDT
                <span v-if="portfolioReport.account_equity_usdt">
                  · 权益 {{ usdt(portfolioReport.account_equity_usdt) }}
                  <span v-if="portfolioReport.var_pct_of_equity != null">
                    · 99% VaR 占权益 {{ pct(portfolioReport.var_pct_of_equity) }}
                  </span>
                </span>
                <span v-if="portfolioReport.diversification_ratio != null">
                  · 分散化比 {{ portfolioReport.diversification_ratio }}
                </span>
              </p>

              <el-table
                :data="portfolioReport.positions || []"
                size="small"
                stripe
                class="mt"
                empty-text="无持仓"
              >
                <el-table-column prop="base" label="标的" width="72" />
                <el-table-column prop="side" label="方向" width="72" />
                <el-table-column label="名义" width="100">
                  <template #default="{ row }">{{ usdt(row.notional_usdt) }}</template>
                </el-table-column>
                <el-table-column label="权重" width="72">
                  <template #default="{ row }">
                    {{ row.weight != null ? (row.weight * 100).toFixed(1) + "%" : "—" }}
                  </template>
                </el-table-column>
                <el-table-column label="成分 VaR" width="100">
                  <template #default="{ row }">{{ usdt(row.standalone_var_usdt) }}</template>
                </el-table-column>
                <el-table-column label="边际贡献" width="100">
                  <template #default="{ row }">{{ usdt(row.var_contribution_usdt) }}</template>
                </el-table-column>
                <el-table-column label="贡献%" width="72">
                  <template #default="{ row }">
                    {{ row.var_contribution_pct != null ? row.var_contribution_pct + "%" : "—" }}
                  </template>
                </el-table-column>
              </el-table>

              <el-row v-if="portfolioReport.correlation?.matrix?.length" :gutter="16" class="mt">
                <el-col :span="14">
                  <el-card shadow="never" class="inner-card">
                    <template #header>收益相关性</template>
                    <el-table
                      :data="portfolioReport.correlation.symbols.map((s, i) => ({
                        symbol: s,
                        values: portfolioReport.correlation!.matrix[i],
                      }))"
                      size="small"
                      stripe
                    >
                      <el-table-column prop="symbol" label="" width="64" />
                      <el-table-column
                        v-for="(col, j) in portfolioReport.correlation.symbols"
                        :key="col"
                        :label="col"
                        width="72"
                      >
                        <template #default="{ row }">
                          {{ row.values[j] != null ? row.values[j].toFixed(2) : "—" }}
                        </template>
                      </el-table-column>
                    </el-table>
                  </el-card>
                </el-col>
                <el-col :span="10">
                  <el-card shadow="never" class="inner-card">
                    <template #header>组合压力情景</template>
                    <el-table :data="portfolioReport.stress_scenarios || []" size="small" stripe>
                      <el-table-column prop="shock_pct" label="冲击 %" width="88" />
                      <el-table-column label="损失 USDT">
                        <template #default="{ row }">{{ usdt(row.loss_usdt) }}</template>
                      </el-table-column>
                    </el-table>
                  </el-card>
                </el-col>
              </el-row>
            </template>
          </template>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
}
.mb {
  margin-bottom: 12px;
}
.mt {
  margin-top: 16px;
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
.small {
  font-size: 11px;
}
.stat-card {
  margin-bottom: 8px;
}
.stat-label {
  font-size: 12px;
  color: var(--text-muted);
}
.stat-val {
  font-size: 1.35rem;
  font-weight: 600;
  margin-top: 4px;
}
.stat-val.warn {
  color: var(--el-color-warning);
}
.stat-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 6px;
}
.stat-sub.text-ok {
  color: var(--el-color-success);
}
.mc-line {
  line-height: 1.45;
}
.inner-card {
  background: transparent;
}
.symbol-form {
  margin-bottom: 8px;
}
.narrative-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 13px;
}
.hist-chart,
.rolling-chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 88px;
  padding: 8px 0;
}
.hist-bar-wrap,
.rolling-bar-wrap {
  flex: 1;
  display: flex;
  align-items: flex-end;
  min-width: 4px;
  height: 100%;
}
.hist-bar {
  width: 100%;
  background: var(--el-color-primary-light-5);
  border-radius: 2px 2px 0 0;
}
.rolling-bar {
  width: 100%;
  background: var(--el-color-warning-light-5);
  border-radius: 2px 2px 0 0;
}
.rolling-bar-wrap.breach .rolling-bar {
  background: var(--el-color-danger);
}
</style>
