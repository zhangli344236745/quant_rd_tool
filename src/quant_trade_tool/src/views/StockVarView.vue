<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  stocksApi,
  type StockPortfolioVarReport,
  type StockSymbolVarHistory,
  type StockSymbolVarReport,
  type StockVarHolding,
  type StockVarMetric,
} from "@/api/stocks";
import { extractError } from "@/api/http";

const route = useRoute();
const router = useRouter();

const activeTab = ref<"symbol" | "portfolio">("symbol");

const symbolForm = ref({
  symbol: "600519",
  notional_cny: 100000,
  lookback_bars: 252,
  horizon_days: 1,
  conf90: false,
  conf95: true,
  conf99: true,
  mc_n_sims: 10000,
});

const portfolioHoldings = ref<StockVarHolding[]>([
  { symbol: "600519", notional_cny: 100000 },
  { symbol: "000001", notional_cny: 80000 },
]);

const symbolLoading = ref(false);
const symbolError = ref("");
const symbolReport = ref<StockSymbolVarReport | null>(null);
const historyLoading = ref(false);
const symbolHistory = ref<StockSymbolVarHistory | null>(null);

const portfolioLoading = ref(false);
const portfolioError = ref("");
const portfolioReport = ref<StockPortfolioVarReport | null>(null);

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

function cny(v: number | undefined | null) {
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

function metricAt(
  metrics: Record<string, StockVarMetric> | null | undefined,
  key: string,
): StockVarMetric | undefined {
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
  const sym = String(route.query.symbol || "").replace(/^(SH|SZ)/i, "");
  if (/^\d{6}$/.test(sym)) symbolForm.value.symbol = sym;
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
  pushRouteQuery();
  try {
    const { data } = await stocksApi.varSymbol({
      symbol: symbolForm.value.symbol,
      notional_cny: symbolForm.value.notional_cny,
      lookback_bars: symbolForm.value.lookback_bars,
      horizon_days: symbolForm.value.horizon_days,
      confidence: confidenceParam(),
      mc_n_sims: symbolForm.value.mc_n_sims,
    });
    symbolReport.value = data;
    await loadSymbolHistory();
  } catch (e) {
    symbolError.value = extractError(e);
    ElMessage.error(symbolError.value);
  } finally {
    symbolLoading.value = false;
  }
}

async function loadSymbolHistory() {
  const conf = symbolForm.value.conf99 ? 0.99 : symbolForm.value.conf95 ? 0.95 : 0.9;
  historyLoading.value = true;
  try {
    const { data } = await stocksApi.varSymbolHistory({
      symbol: symbolForm.value.symbol,
      window: 60,
      confidence: conf,
      lookback_bars: symbolForm.value.lookback_bars,
      horizon_days: symbolForm.value.horizon_days,
      notional_cny: symbolForm.value.notional_cny,
    });
    symbolHistory.value = data;
  } catch {
    symbolHistory.value = null;
  } finally {
    historyLoading.value = false;
  }
}

function addHolding() {
  portfolioHoldings.value.push({ symbol: "000001", notional_cny: 50000 });
}

function removeHolding(idx: number) {
  if (portfolioHoldings.value.length > 1) {
    portfolioHoldings.value.splice(idx, 1);
  }
}

async function loadPortfolioVar() {
  portfolioLoading.value = true;
  portfolioError.value = "";
  portfolioReport.value = null;
  pushRouteQuery();
  try {
    const { data } = await stocksApi.varPortfolio({
      holdings: portfolioHoldings.value,
      lookback_bars: symbolForm.value.lookback_bars,
      horizon_days: symbolForm.value.horizon_days,
      confidence: confidenceParam(),
      mc_n_sims: symbolForm.value.mc_n_sims,
    });
    portfolioReport.value = data;
  } catch (e) {
    portfolioError.value = extractError(e);
    ElMessage.error(portfolioError.value);
  } finally {
    portfolioLoading.value = false;
  }
}

function histBarStyle(bin: { count: number }) {
  const h = Math.round((bin.count / histMax.value) * 100);
  return { height: `${Math.max(4, h)}%` };
}

function rollingBarStyle(varPct: number) {
  const h = Math.round((varPct / rollingMaxVar.value) * 100);
  return { height: `${Math.max(6, h)}%` };
}

watch(activeTab, () => pushRouteQuery());
watch(() => route.query, () => syncFromRoute());

onMounted(() => {
  syncFromRoute();
});
</script>

<template>
  <div>
    <h1 class="page-title">A股 风险 VaR</h1>
    <p class="page-desc">
      基于日线历史模拟的 VaR / CVaR，含参数法、蒙特卡洛（GBM / Student-t）、回测与压力情景；组合支持自定义持仓名义。
    </p>

    <el-card shadow="never" class="panel-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="单标的" name="symbol">
          <el-form label-width="120px" size="small" class="symbol-form">
            <el-row :gutter="16">
              <el-col :span="6">
                <el-form-item label="标的">
                  <el-select v-model="symbolForm.symbol" filterable style="width: 100%">
                    <el-option label="600519 茅台" value="600519" />
                    <el-option label="000001 平安" value="000001" />
                    <el-option label="300750 宁德" value="300750" />
                    <el-option label="601318 平安" value="601318" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="名义 (元)">
                  <el-input-number v-model="symbolForm.notional_cny" :min="0" :step="10000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="回看 K 线">
                  <el-input-number v-model="symbolForm.lookback_bars" :min="30" :max="2000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="持有期 (天)">
                  <el-input-number v-model="symbolForm.horizon_days" :min="1" :max="30" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
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
              {{ symbolReport.symbol }} · 收盘 {{ symbolReport.latest_price }} · 名义 {{ cny(symbolReport.notional_cny) }} 元
              · 样本 {{ symbolReport.observations }} 期
              <span v-if="symbolReport.return_stats?.annualized_volatility != null">
                · 年化波动 {{ pct(symbolReport.return_stats.annualized_volatility) }}
              </span>
            </p>

            <el-row :gutter="12">
              <el-col v-for="key in symbolMetricKeys" :key="key" :span="12">
                <el-card shadow="never" class="stat-card">
                  <div class="stat-label">{{ symbolForm.horizon_days }} 日 {{ confLabel(key) }} 风险</div>
                  <div class="stat-val warn">VaR {{ cny(metricAt(symbolReport.metrics, key)?.var_cny) }} 元</div>
                  <div class="stat-sub">
                    历史 {{ pct(metricAt(symbolReport.metrics, key)?.var_pct) }} · 参数
                    {{ pct(metricAt(symbolReport.metrics, key)?.parametric_var_pct) }} · CVaR
                    {{ cny(metricAt(symbolReport.metrics, key)?.cvar_cny) }} 元
                  </div>
                  <div v-if="metricAt(symbolReport.metrics, key)?.monte_carlo" class="stat-sub mc-line">
                    MC·GBM {{ cny(metricAt(symbolReport.metrics, key)?.monte_carlo?.gbm.var_cny) }}
                    · MC·t {{ cny(metricAt(symbolReport.metrics, key)?.monte_carlo?.student_t.var_cny) }}
                  </div>
                </el-card>
              </el-col>
            </el-row>

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
                </el-card>
              </el-col>
              <el-col :span="12">
                <el-card shadow="never" class="inner-card">
                  <template #header>压力情景</template>
                  <el-table :data="symbolReport.stress_scenarios || []" size="small" stripe>
                    <el-table-column prop="shock_pct" label="冲击 %" width="88" />
                    <el-table-column label="损失 (元)">
                      <template #default="{ row }">{{ cny(row.loss_cny) }}</template>
                    </el-table-column>
                  </el-table>
                </el-card>
              </el-col>
            </el-row>

            <el-card v-loading="historyLoading" shadow="never" class="panel-card mt inner-card">
              <template #header>
                滚动 VaR（近 60 窗）
                <span v-if="symbolHistory?.breach_count != null" class="muted small">
                  · 突破 {{ symbolHistory.breach_count }} 次
                </span>
              </template>
              <div v-if="symbolHistory?.series?.length" class="rolling-chart">
                <div
                  v-for="(pt, i) in symbolHistory.series"
                  :key="i"
                  class="rolling-bar-wrap"
                  :class="{ breach: pt.breach }"
                  :title="`${pt.date}: VaR ${pct(pt.var_pct)}`"
                >
                  <div class="rolling-bar" :style="rollingBarStyle(pt.var_pct)" />
                </div>
              </div>
            </el-card>
          </template>
        </el-tab-pane>

        <el-tab-pane label="组合" name="portfolio">
          <p class="muted small mb">自定义持仓名义（元）；回看 / 持有期 / 置信度与单标的页共用。</p>
          <div class="holdings-form">
            <div v-for="(h, idx) in portfolioHoldings" :key="idx" class="holding-row">
              <el-input v-model="h.symbol" placeholder="代码" style="width: 120px" size="small" />
              <span class="leg-w">名义</span>
              <el-input-number v-model="h.notional_cny" :min="1000" :step="10000" size="small" />
              <el-button v-if="portfolioHoldings.length > 1" link type="danger" size="small" @click="removeHolding(idx)">
                删除
              </el-button>
            </div>
            <el-button size="small" @click="addHolding">添加持仓</el-button>
            <el-button type="primary" :loading="portfolioLoading" class="ml" @click="loadPortfolioVar">
              计算组合 VaR
            </el-button>
          </div>

          <el-alert v-if="portfolioError" type="error" :title="portfolioError" show-icon class="mb mt" />

          <template v-if="portfolioReport">
            <el-alert
              v-if="portfolioReport.message"
              type="info"
              :title="portfolioReport.message"
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
            />

            <el-row v-if="portfolioReport.metrics" :gutter="12" class="mt">
              <el-col v-for="key in portfolioMetricKeys" :key="key" :span="12">
                <el-card shadow="never" class="stat-card">
                  <div class="stat-label">组合 {{ confLabel(key) }} VaR</div>
                  <div class="stat-val warn">{{ cny(metricAt(portfolioReport.metrics, key)?.var_cny) }} 元</div>
                  <div class="stat-sub">
                    CVaR {{ cny(metricAt(portfolioReport.metrics, key)?.cvar_cny) }} 元
                  </div>
                </el-card>
              </el-col>
            </el-row>

            <p v-if="portfolioReport.gross_exposure_cny != null" class="muted small mt">
              总敞口 {{ cny(portfolioReport.gross_exposure_cny) }} 元 · 净敞口
              {{ cny(portfolioReport.net_exposure_cny) }} 元
              <span v-if="portfolioReport.diversification_ratio != null">
                · 分散化比 {{ portfolioReport.diversification_ratio }}
              </span>
            </p>

            <el-table :data="portfolioReport.positions || []" size="small" stripe class="mt" empty-text="无持仓">
              <el-table-column prop="qlib_code" label="标的" width="100" />
              <el-table-column prop="side" label="方向" width="72" />
              <el-table-column label="名义" width="110">
                <template #default="{ row }">{{ cny(row.notional_cny) }}</template>
              </el-table-column>
              <el-table-column label="权重" width="72">
                <template #default="{ row }">
                  {{ row.weight != null ? (row.weight * 100).toFixed(1) + "%" : "—" }}
                </template>
              </el-table-column>
              <el-table-column label="成分 VaR" width="100">
                <template #default="{ row }">{{ cny(row.standalone_var_cny) }}</template>
              </el-table-column>
              <el-table-column label="边际贡献" width="100">
                <template #default="{ row }">{{ cny(row.var_contribution_cny) }}</template>
              </el-table-column>
            </el-table>
          </template>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.page-title {
  margin: 0 0 8px;
  font-size: 22px;
}
.page-desc {
  margin: 0 0 16px;
  color: var(--text-muted);
  font-size: 14px;
}
.panel-card {
  margin-bottom: 0;
}
.mb {
  margin-bottom: 12px;
}
.mt {
  margin-top: 16px;
}
.ml {
  margin-left: 8px;
}
.muted {
  color: var(--text-muted);
}
.small {
  font-size: 11px;
}
.symbol-form {
  margin-bottom: 8px;
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
.mc-line {
  line-height: 1.45;
}
.inner-card {
  background: transparent;
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
.holdings-form {
  margin-bottom: 12px;
}
.holding-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.leg-w {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
