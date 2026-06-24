<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  stocksApi,
  type StockVbtBacktestResult,
  type StockVbtMlScoreResult,
  type StockVbtPortfolioResult,
  type StockVbtRunSummary,
  type StockVbtSchedulerStatus,
  type StockVbtStrategy,
  type StockVbtTuneResult,
} from "@/api/stocks";
import { extractError } from "@/api/http";
import { formatBeijing } from "@/utils/datetime";

function formatTimeCol(_r: unknown, _c: unknown, v: string) {
  return formatBeijing(v);
}
import EquityCurveChart from "@/components/EquityCurveChart.vue";

const activeTab = ref("backtest");
const loading = ref(false);
const running = ref(false);
const strategies = ref<StockVbtStrategy[]>([]);
const runs = ref<StockVbtRunSummary[]>([]);
const result = ref<StockVbtBacktestResult | null>(null);

const form = ref({
  symbol: "600519",
  start: "2022-01-01",
  end: new Date().toISOString().slice(0, 10),
  strategy_id: "sma_cross",
  capital_base: 100_000,
  refresh_data: false,
});

const paramValues = ref<Record<string, number>>({});

const tuneForm = ref({
  symbol: "600519",
  start: "2022-01-01",
  end: new Date().toISOString().slice(0, 10),
  strategy_id: "sma_cross",
  n_trials: 20,
  train_ratio: 0.7,
});
const tuneRunning = ref(false);
const tuneResult = ref<StockVbtTuneResult | null>(null);

const mlForm = ref({
  symbolsText: "600519,000001,000858,601318,600036",
  start: "2022-01-01",
  end: new Date().toISOString().slice(0, 10),
  top_k: 5,
  algorithm: "lgb",
  use_watchlist: false,
});
const mlRunning = ref(false);
const mlResult = ref<StockVbtMlScoreResult | null>(null);

const portForm = ref({
  symbolsText: "600519,000001,000858",
  start: "2022-01-01",
  end: new Date().toISOString().slice(0, 10),
  method: "max_sharpe",
  lookback_days: 252,
  with_backtest: true,
});
const portRunning = ref(false);
const portResult = ref<StockVbtPortfolioResult | null>(null);

const schedStatus = ref<StockVbtSchedulerStatus | null>(null);
const schedForm = ref({
  cron_hour: 18,
  cron_minute: 0,
  use_watchlist: true,
  top_k: 5,
  ml_algorithm: "lgb",
  portfolio_method: "max_sharpe",
  strategy_id: "sma_cross",
  start: "2020-01-01",
  refresh_data: true,
  optuna_trials: 0,
});
const schedLoading = ref(false);

const activeStrategy = computed(() =>
  strategies.value.find((s) => s.id === form.value.strategy_id),
);

function syncParamsFromStrategy() {
  const s = activeStrategy.value;
  if (!s) return;
  const next: Record<string, number> = {};
  for (const p of s.param_schema) {
    next[p.name] = s.default_params[p.name] ?? p.default;
  }
  paramValues.value = next;
}

watch(
  () => form.value.strategy_id,
  () => syncParamsFromStrategy(),
);

function pct(v: number | undefined | null, digits = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return (v * 100).toFixed(digits) + "%";
}

function num(v: number | undefined | null, digits = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function parseSymbols(text: string): string[] {
  return text
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

const metricCards = computed(() => {
  const m = result.value?.metrics as Record<string, number> | undefined;
  if (!m) return [];
  return [
    { label: "总收益", value: pct(m.total_return) },
    { label: "年化 CAGR", value: pct(m.cagr) },
    { label: "夏普", value: num(m.sharpe) },
    { label: "最大回撤", value: pct(m.max_drawdown) },
    { label: "胜率", value: pct(m.win_rate) },
    { label: "波动率", value: pct(m.volatility) },
  ];
});

async function loadMeta() {
  loading.value = true;
  try {
    const [sRes, rRes] = await Promise.all([
      stocksApi.vbtStrategies(),
      stocksApi.vbtRuns({ limit: 15 }),
    ]);
    strategies.value = sRes.data ?? [];
    runs.value = rRes.data?.items ?? [];
    if (!form.value.strategy_id && strategies.value.length) {
      form.value.strategy_id = strategies.value[0].id;
    }
    syncParamsFromStrategy();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

async function loadScheduler() {
  schedLoading.value = true;
  try {
    const { data } = await stocksApi.vbtSchedulerStatus();
    schedStatus.value = data;
    const cfg = data?.config ?? {};
    schedForm.value = {
      cron_hour: Number(cfg.cron_hour ?? 18),
      cron_minute: Number(cfg.cron_minute ?? 0),
      use_watchlist: Boolean(cfg.use_watchlist ?? true),
      top_k: Number(cfg.top_k ?? 5),
      ml_algorithm: String(cfg.ml_algorithm ?? "lgb"),
      portfolio_method: String(cfg.portfolio_method ?? "max_sharpe"),
      strategy_id: String(cfg.strategy_id ?? "sma_cross"),
      start: String(cfg.start ?? "2020-01-01"),
      refresh_data: Boolean(cfg.refresh_data ?? true),
      optuna_trials: Number(cfg.optuna_trials ?? 0),
    };
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    schedLoading.value = false;
  }
}

async function applyTuneToBacktest() {
  if (!tuneResult.value) return;
  form.value.symbol = tuneResult.value.symbol.replace(/^(SH|SZ)/i, "");
  form.value.strategy_id = tuneResult.value.strategy_id;
  paramValues.value = { ...tuneResult.value.best_params };
  activeTab.value = "backtest";
  ElMessage.success("已填入最优参数，可运行回测");
}

async function runBacktestAsync() {
  running.value = true;
  try {
    const { data } = await stocksApi.vbtBacktestJob({
      symbol: form.value.symbol.trim(),
      start: form.value.start,
      end: form.value.end,
      strategy_id: form.value.strategy_id,
      strategy_params: { ...paramValues.value },
      capital_base: form.value.capital_base,
      refresh_data: form.value.refresh_data,
    });
    ElMessage.success(`异步任务已提交：${data.job_id}`);
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    running.value = false;
  }
}

async function runBacktest() {
  running.value = true;
  result.value = null;
  try {
    const { data } = await stocksApi.vbtBacktest({
      symbol: form.value.symbol.trim(),
      start: form.value.start,
      end: form.value.end,
      strategy_id: form.value.strategy_id,
      strategy_params: { ...paramValues.value },
      capital_base: form.value.capital_base,
      refresh_data: form.value.refresh_data,
    });
    result.value = data;
    ElMessage.success("回测完成");
    const rRes = await stocksApi.vbtRuns({ limit: 15 });
    runs.value = rRes.data?.items ?? [];
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    running.value = false;
  }
}

async function runTune() {
  tuneRunning.value = true;
  tuneResult.value = null;
  try {
    const { data } = await stocksApi.vbtTune({
      symbol: tuneForm.value.symbol.trim(),
      start: tuneForm.value.start,
      end: tuneForm.value.end,
      strategy_id: tuneForm.value.strategy_id,
      n_trials: tuneForm.value.n_trials,
      train_ratio: tuneForm.value.train_ratio,
    });
    tuneResult.value = data;
    ElMessage.success("调参完成");
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    tuneRunning.value = false;
  }
}

async function runMlScore() {
  mlRunning.value = true;
  mlResult.value = null;
  try {
    const symbols = parseSymbols(mlForm.value.symbolsText);
    const { data } = await stocksApi.vbtMlScore({
      symbols: mlForm.value.use_watchlist ? undefined : symbols,
      start: mlForm.value.start,
      end: mlForm.value.end,
      top_k: mlForm.value.top_k,
      algorithm: mlForm.value.algorithm,
      use_watchlist: mlForm.value.use_watchlist,
    });
    mlResult.value = data;
    ElMessage.success(`选股完成，${data.items?.length ?? 0} 只入选`);
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    mlRunning.value = false;
  }
}

async function runPortfolio() {
  portRunning.value = true;
  portResult.value = null;
  try {
    const symbols = parseSymbols(portForm.value.symbolsText);
    const { data } = await stocksApi.vbtPortfolioOptimize({
      symbols,
      start: portForm.value.start,
      end: portForm.value.end,
      method: portForm.value.method,
      lookback_days: portForm.value.lookback_days,
      with_backtest: portForm.value.with_backtest,
    });
    portResult.value = data;
    ElMessage.success("组合优化完成");
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    portRunning.value = false;
  }
}

async function saveSchedulerConfig() {
  schedLoading.value = true;
  try {
    await stocksApi.vbtSchedulerConfig({ ...schedForm.value });
    await loadScheduler();
    ElMessage.success("调度配置已保存");
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    schedLoading.value = false;
  }
}

async function startScheduler() {
  try {
    const { data } = await stocksApi.vbtSchedulerStart();
    schedStatus.value = data;
    ElMessage.success("定时任务已启动");
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function stopScheduler() {
  try {
    const { data } = await stocksApi.vbtSchedulerStop();
    schedStatus.value = data;
    ElMessage.success("定时任务已停止");
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function triggerScheduler() {
  schedLoading.value = true;
  try {
    await stocksApi.vbtSchedulerTrigger();
    await loadScheduler();
    ElMessage.success("流水线执行完成");
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    schedLoading.value = false;
  }
}

onMounted(async () => {
  await loadMeta();
  await loadScheduler();
});
</script>

<template>
  <div class="page">
    <header class="head">
      <div>
        <h1>A股 VectorBT 实验室</h1>
        <p class="sub">
          AkShare 日线 + VectorBT 信号 + A 股执行规则 + Optuna / ML 选股 / 组合优化。
        </p>
      </div>
      <el-button :loading="loading" @click="loadMeta">刷新</el-button>
    </header>

    <el-tabs v-model="activeTab" class="mb">
      <el-tab-pane label="单股回测" name="backtest">
        <el-row :gutter="16">
          <el-col :span="10">
            <el-card shadow="never" v-loading="loading">
              <template #header>回测参数</template>
              <el-form label-width="100px">
                <el-form-item label="股票代码">
                  <el-input v-model="form.symbol" placeholder="600519" style="width: 160px" />
                </el-form-item>
                <el-form-item label="日期区间">
                  <el-date-picker
                    v-model="form.start"
                    type="date"
                    value-format="YYYY-MM-DD"
                    placeholder="开始"
                    style="width: 140px; margin-right: 8px"
                  />
                  <el-date-picker
                    v-model="form.end"
                    type="date"
                    value-format="YYYY-MM-DD"
                    placeholder="结束"
                    style="width: 140px"
                  />
                </el-form-item>
                <el-form-item label="策略">
                  <el-select v-model="form.strategy_id" style="width: 100%">
                    <el-option
                      v-for="s in strategies"
                      :key="s.id"
                      :label="s.name"
                      :value="s.id"
                    >
                      <span>{{ s.name }}</span>
                      <span class="hint"> — {{ s.description }}</span>
                    </el-option>
                  </el-select>
                </el-form-item>
                <el-form-item
                  v-for="p in activeStrategy?.param_schema ?? []"
                  :key="p.name"
                  :label="p.label"
                >
                  <el-input-number
                    v-model="paramValues[p.name]"
                    :min="p.min"
                    :max="p.max"
                    :step="p.type === 'int' ? 1 : 0.1"
                  />
                </el-form-item>
                <el-form-item label="初始资金">
                  <el-input-number v-model="form.capital_base" :min="10000" :step="10000" /> 元
                </el-form-item>
                <el-form-item label="刷新行情">
                  <el-switch v-model="form.refresh_data" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="running" @click="runBacktest">运行回测</el-button>
                  <el-button :loading="running" @click="runBacktestAsync">异步回测</el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>
          <el-col :span="14">
            <el-card shadow="never" class="mb">
              <template #header>
                <span>绩效摘要</span>
              </template>
              <el-empty v-if="!result" description="运行回测后显示指标" />
              <el-row v-else :gutter="12">
                <el-col v-for="c in metricCards" :key="c.label" :span="8" class="metric-col">
                  <div class="metric-label">{{ c.label }}</div>
                  <div class="metric-value">{{ c.value }}</div>
                </el-col>
              </el-row>
            </el-card>
            <el-card v-if="result?.equity_curve?.length" shadow="never" class="mb">
              <template #header>净值曲线</template>
              <EquityCurveChart :points="result.equity_curve" />
            </el-card>
            <el-card v-if="result?.trades?.length" shadow="never">
              <template #header>成交明细（{{ result.trades_count }} 笔）</template>
              <el-table :data="result.trades" size="small" stripe max-height="280">
                <el-table-column prop="time" label="时间" min-width="120" />
                <el-table-column prop="side" label="方向" width="70" />
                <el-table-column prop="price" label="价格" width="90" />
                <el-table-column prop="shares" label="股数" width="90" />
                <el-table-column prop="fee" label="费用" width="80" />
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="自动调参" name="tune">
        <el-row :gutter="16">
          <el-col :span="10">
            <el-card shadow="never">
              <template #header>Optuna 调参</template>
              <el-form label-width="100px">
                <el-form-item label="股票">
                  <el-input v-model="tuneForm.symbol" style="width: 140px" />
                </el-form-item>
                <el-form-item label="区间">
                  <el-date-picker v-model="tuneForm.start" type="date" value-format="YYYY-MM-DD" style="width: 130px; margin-right: 6px" />
                  <el-date-picker v-model="tuneForm.end" type="date" value-format="YYYY-MM-DD" style="width: 130px" />
                </el-form-item>
                <el-form-item label="策略">
                  <el-select v-model="tuneForm.strategy_id" style="width: 100%">
                    <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
                  </el-select>
                </el-form-item>
                <el-form-item label="试验次数">
                  <el-input-number v-model="tuneForm.n_trials" :min="5" :max="100" />
                </el-form-item>
                <el-form-item label="训练占比">
                  <el-input-number v-model="tuneForm.train_ratio" :min="0.5" :max="0.9" :step="0.05" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="tuneRunning" @click="runTune">开始调参</el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>
          <el-col :span="14">
            <el-card v-if="tuneResult" shadow="never">
              <template #header>最优参数（样本内夏普 {{ num(tuneResult.best_sharpe) }}）</template>
              <p><strong>参数：</strong>{{ JSON.stringify(tuneResult.best_params) }}</p>
              <el-row :gutter="12" class="mt">
                <el-col :span="12">
                  <div class="metric-label">训练集夏普</div>
                  <div class="metric-value">{{ num(tuneResult.train_metrics?.sharpe) }}</div>
                </el-col>
                <el-col :span="12">
                  <div class="metric-label">测试集夏普</div>
                  <div class="metric-value">{{ num(tuneResult.test_metrics?.sharpe) }}</div>
                </el-col>
              </el-row>
              <el-button class="mt" type="primary" @click="applyTuneToBacktest">用最优参数回测</el-button>
            </el-card>
            <el-empty v-else description="调参完成后显示结果" />
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="ML 选股" name="ml">
        <el-row :gutter="16">
          <el-col :span="10">
            <el-card shadow="never">
              <template #header>截面打分</template>
              <el-form label-width="100px">
                <el-form-item label="股票列表">
                  <el-input
                    v-model="mlForm.symbolsText"
                    type="textarea"
                    :rows="2"
                    placeholder="600519,000001"
                    :disabled="mlForm.use_watchlist"
                  />
                </el-form-item>
                <el-form-item label="用自选">
                  <el-switch v-model="mlForm.use_watchlist" />
                </el-form-item>
                <el-form-item label="区间">
                  <el-date-picker v-model="mlForm.start" type="date" value-format="YYYY-MM-DD" style="width: 130px; margin-right: 6px" />
                  <el-date-picker v-model="mlForm.end" type="date" value-format="YYYY-MM-DD" style="width: 130px" />
                </el-form-item>
                <el-form-item label="Top-K">
                  <el-input-number v-model="mlForm.top_k" :min="1" :max="30" />
                </el-form-item>
                <el-form-item label="算法">
                  <el-select v-model="mlForm.algorithm" style="width: 120px">
                    <el-option label="LightGBM" value="lgb" />
                    <el-option label="XGBoost" value="xgb" />
                  </el-select>
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="mlRunning" @click="runMlScore">运行选股</el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>
          <el-col :span="14">
            <el-card v-if="mlResult" shadow="never">
              <template #header>Top-{{ mlResult.items?.length }} 排名</template>
              <el-table :data="mlResult.items" size="small" stripe>
                <el-table-column prop="symbol" label="代码" width="120" />
                <el-table-column label="得分" width="120">
                  <template #default="{ row }">{{ num(row.score, 4) }}</template>
                </el-table-column>
                <el-table-column label="预期5日收益">
                  <template #default="{ row }">{{ pct(row.expected_fwd_return_5d) }}</template>
                </el-table-column>
              </el-table>
            </el-card>
            <el-empty v-else description="选股完成后显示排名" />
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="组合优化" name="portfolio">
        <el-row :gutter="16">
          <el-col :span="10">
            <el-card shadow="never">
              <template #header>PyPortfolioOpt</template>
              <el-form label-width="100px">
                <el-form-item label="成分股">
                  <el-input v-model="portForm.symbolsText" type="textarea" :rows="2" />
                </el-form-item>
                <el-form-item label="区间">
                  <el-date-picker v-model="portForm.start" type="date" value-format="YYYY-MM-DD" style="width: 130px; margin-right: 6px" />
                  <el-date-picker v-model="portForm.end" type="date" value-format="YYYY-MM-DD" style="width: 130px" />
                </el-form-item>
                <el-form-item label="方法">
                  <el-select v-model="portForm.method" style="width: 160px">
                    <el-option label="最大夏普" value="max_sharpe" />
                    <el-option label="最小波动" value="min_volatility" />
                  </el-select>
                </el-form-item>
                <el-form-item label="回看天数">
                  <el-input-number v-model="portForm.lookback_days" :min="30" :max="500" />
                </el-form-item>
                <el-form-item label="回测净值">
                  <el-switch v-model="portForm.with_backtest" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="portRunning" @click="runPortfolio">优化组合</el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>
          <el-col :span="14">
            <el-card v-if="portResult" shadow="never">
              <template #header>权重 · 夏普 {{ num(portResult.sharpe_ratio) }}</template>
              <el-table :data="Object.entries(portResult.weights).map(([symbol, weight]) => ({ symbol, weight }))" size="small">
                <el-table-column prop="symbol" label="代码" />
                <el-table-column label="权重">
                  <template #default="{ row }">{{ pct(row.weight) }}</template>
                </el-table-column>
              </el-table>
              <el-card v-if="portResult.backtest?.equity_curve?.length" shadow="never" class="mt">
                <template #header>组合净值（收益 {{ pct(portResult.backtest.total_return) }}）</template>
                <EquityCurveChart :points="portResult.backtest.equity_curve" />
              </el-card>
            </el-card>
            <el-empty v-else description="优化完成后显示权重" />
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="定时流水线" name="scheduler">
        <el-row :gutter="16">
          <el-col :span="10">
            <el-card shadow="never" v-loading="schedLoading">
              <template #header>每日 ML → 组合 → 信号</template>
              <el-form label-width="110px">
                <el-form-item label="Cron 时:分">
                  <el-input-number v-model="schedForm.cron_hour" :min="0" :max="23" />
                  :
                  <el-input-number v-model="schedForm.cron_minute" :min="0" :max="59" />
                </el-form-item>
                <el-form-item label="用自选池">
                  <el-switch v-model="schedForm.use_watchlist" />
                </el-form-item>
                <el-form-item label="Top-K">
                  <el-input-number v-model="schedForm.top_k" :min="1" :max="20" />
                </el-form-item>
                <el-form-item label="ML 算法">
                  <el-select v-model="schedForm.ml_algorithm" style="width: 120px">
                    <el-option label="LightGBM" value="lgb" />
                    <el-option label="XGBoost" value="xgb" />
                  </el-select>
                </el-form-item>
                <el-form-item label="组合方法">
                  <el-select v-model="schedForm.portfolio_method" style="width: 160px">
                    <el-option label="最大夏普" value="max_sharpe" />
                    <el-option label="最小波动" value="min_volatility" />
                  </el-select>
                </el-form-item>
                <el-form-item label="数据起点">
                  <el-date-picker v-model="schedForm.start" type="date" value-format="YYYY-MM-DD" />
                </el-form-item>
                <el-form-item label="刷新行情">
                  <el-switch v-model="schedForm.refresh_data" />
                </el-form-item>
                <el-form-item label="Optuna 试验">
                  <el-input-number v-model="schedForm.optuna_trials" :min="0" :max="50" />
                  <span class="hint"> 0=跳过；对 Top1 调参</span>
                </el-form-item>
                <el-form-item label="策略模板">
                  <el-select v-model="schedForm.strategy_id" style="width: 160px">
                    <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
                  </el-select>
                </el-form-item>
                <el-form-item>
                  <el-button @click="saveSchedulerConfig">保存配置</el-button>
                  <el-button type="success" @click="startScheduler">启动</el-button>
                  <el-button @click="stopScheduler">停止</el-button>
                  <el-button type="primary" :loading="schedLoading" @click="triggerScheduler">立即执行</el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>
          <el-col :span="14">
            <el-card shadow="never">
              <template #header>
                状态
                <el-tag v-if="schedStatus?.running" type="success" size="small" class="ml">运行中</el-tag>
                <el-tag v-else type="info" size="small" class="ml">已停止</el-tag>
              </template>
              <p v-if="schedStatus?.last_run_at">上次运行：{{ formatBeijing(schedStatus.last_run_at) }}</p>
              <p v-if="schedStatus?.last_error" class="err">错误：{{ schedStatus.last_error }}</p>
              <el-table
                v-if="schedStatus?.latest_signals?.ml_rankings"
                :data="(schedStatus.latest_signals.ml_rankings as any[])"
                size="small"
                class="mt"
              >
                <el-table-column prop="symbol" label="代码" />
                <el-table-column label="得分">
                  <template #default="{ row }">{{ num(row.score, 4) }}</template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>

    <el-card shadow="never">
      <template #header>最近回测</template>
      <el-table :data="runs" size="small" stripe>
        <el-table-column prop="symbol" label="代码" width="110" />
        <el-table-column prop="strategy_name" label="策略" min-width="120" />
        <el-table-column label="总收益" width="90">
          <template #default="{ row }">{{ pct(row.total_return) }}</template>
        </el-table-column>
        <el-table-column label="夏普" width="80">
          <template #default="{ row }">{{ num(row.sharpe) }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" min-width="160" :formatter="formatTimeCol" />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  padding: 16px 20px 32px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.head h1 {
  margin: 0 0 6px;
  font-size: 22px;
}
.sub {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.mb {
  margin-bottom: 16px;
}
.mt {
  margin-top: 12px;
}
.ml {
  margin-left: 8px;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.err {
  color: var(--el-color-danger);
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.metric-col {
  margin-bottom: 12px;
}
.metric-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.metric-value {
  font-size: 20px;
  font-weight: 600;
  margin-top: 4px;
}
</style>
