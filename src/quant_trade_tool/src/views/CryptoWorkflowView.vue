<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  cryptoApi,
  type CryptoWorkflowRunResult,
  type CryptoWorkflowRunSummary,
  type CryptoWorkflowStepConfig,
  type CryptoWorkflowStepDef,
  type CryptoWorkflowTemplate,
} from "@/api/crypto";
import { extractError } from "@/api/http";
import { jobsApi } from "@/api/jobs";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const running = ref(false);
const stepCatalog = ref<CryptoWorkflowStepDef[]>([]);
const templates = ref<CryptoWorkflowTemplate[]>([]);
const strategies = ref<Array<{ id: string; name: string; category?: string }>>([]);
const runs = ref<CryptoWorkflowRunSummary[]>([]);
const result = ref<CryptoWorkflowRunResult | null>(null);

const selectedTemplateId = ref("");
const templateName = ref("");
const symbol = ref("BTC");
const timeframe = ref("1d");
const refreshOhlcv = ref(true);
const editSteps = ref<CryptoWorkflowStepConfig[]>([]);
const showMarkdown = ref(false);
const runProgress = ref(0);
const runMessage = ref("");
let pollTimer: ReturnType<typeof setTimeout> | null = null;

const tvStrategies = computed(() =>
  strategies.value.filter((s) => !s.id.startsWith("opt_") && s.category !== "options"),
);

const stepName = (id: string) => stepCatalog.value.find((s) => s.id === id)?.name || id;

const sortedSteps = computed(() => [...editSteps.value].sort((a, b) => a.order - b.order));

const adviceStep = computed(() => sortedSteps.value.find((s) => s.id === "advice_synth"));

function loadTemplateIntoEditor(tpl: CryptoWorkflowTemplate) {
  selectedTemplateId.value = tpl.id || "";
  templateName.value = tpl.name || "";
  symbol.value = tpl.symbol_default || "BTC";
  timeframe.value = tpl.timeframe || "1d";
  editSteps.value = (tpl.steps || []).map((s, i) => ({
    id: s.id,
    enabled: s.enabled !== false,
    order: s.order ?? i,
    params: { ...(s.params || {}) },
  }));
}

async function loadCatalog() {
  const [{ data: steps }, { data: tpls }, { data: strat }, { data: runList }] = await Promise.all([
    cryptoApi.workflowSteps(),
    cryptoApi.workflowTemplates(),
    cryptoApi.ziplineStrategies(),
    cryptoApi.workflowRuns(),
  ]);
  stepCatalog.value = steps.steps;
  templates.value = tpls.templates;
  strategies.value = strat.strategies || [];
  runs.value = runList.runs || [];
  if (!selectedTemplateId.value && templates.value.length) {
    loadTemplateIntoEditor(templates.value[0]);
  }
}

function onSelectTemplate(id: string) {
  const tpl = templates.value.find((t) => t.id === id);
  if (tpl) loadTemplateIntoEditor(tpl);
}

function moveStep(idx: number, dir: -1 | 1) {
  const sorted = sortedSteps.value;
  const pos = sorted.findIndex((s) => s.id === sortedSteps.value[idx]?.id);
  const swap = pos + dir;
  if (swap < 0 || swap >= sorted.length) return;
  const a = sorted[pos];
  const b = sorted[swap];
  const tmp = a.order;
  a.order = b.order;
  b.order = tmp;
}

function stepParams(step: CryptoWorkflowStepConfig): Record<string, unknown> {
  return step.params;
}

function ensureParam(step: CryptoWorkflowStepConfig, key: string, fallback: unknown) {
  if (stepParams(step)[key] === undefined) {
    stepParams(step)[key] = fallback;
  }
}

async function saveTemplate() {
  const body: CryptoWorkflowTemplate = {
    id: selectedTemplateId.value || undefined,
    name: templateName.value || "自定义 Workflow",
    symbol_default: symbol.value,
    timeframe: timeframe.value,
    steps: sortedSteps.value.map((s, i) => ({ ...s, order: i })),
  };
  loading.value = true;
  try {
    const { data } = await cryptoApi.workflowTemplateSave(body);
    ElMessage.success("模板已保存");
    await loadCatalog();
    if (data.template?.id) {
      selectedTemplateId.value = data.template.id;
      templateName.value = data.template.name;
    }
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

async function duplicateTemplate() {
  if (!selectedTemplateId.value) return;
  loading.value = true;
  try {
    const { data } = await cryptoApi.workflowTemplateDuplicate(selectedTemplateId.value);
    ElMessage.success("已复制模板");
    await loadCatalog();
    if (data.template?.id) loadTemplateIntoEditor(data.template);
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

function buildRunPayload() {
  const steps = sortedSteps.value.map((s, i) => ({ ...s, order: i }));
  for (const step of steps) {
    if (step.id === "zipline_strategy") ensureParam(step, "strategy_id", "ma_crossover");
    if (step.id === "var_symbol") ensureParam(step, "notional_usdt", 10000);
    if (step.id === "qlib_ml") {
      ensureParam(step, "algorithm", "both");
      ensureParam(step, "use_cache", true);
    }
    if (step.id === "advice_synth") {
      ensureParam(step, "var_gate_pct", 0.08);
      ensureParam(step, "max_position_pct", 0.5);
      ensureParam(step, "sl_sigma", 1.0);
      ensureParam(step, "tp_sigma", 1.5);
      ensureParam(step, "entry_sigma", 0.35);
    }
  }
  return {
    symbol: symbol.value,
    timeframe: timeframe.value,
    template_id: selectedTemplateId.value || undefined,
    steps,
    refresh_ohlcv: refreshOhlcv.value,
  };
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

async function pollJob(jobId: string) {
  try {
    const { data: job } = await jobsApi.get(jobId);
    runProgress.value = Math.round((job.progress || 0) * 100);
    runMessage.value = job.message || "";
    if (job.status === "done") {
      const { data: snap } = await jobsApi.result(jobId);
      const runId = String(snap.run_id || "");
      if (runId) {
        const { data } = await cryptoApi.workflowRunGet(runId);
        result.value = data;
      }
      await loadCatalog();
      running.value = false;
      stopPolling();
      return;
    }
    if (job.status === "failed" || job.status === "cancelled") {
      ElMessage.error(job.error || `任务${job.status === "failed" ? "失败" : "已取消"}`);
      running.value = false;
      stopPolling();
      return;
    }
    pollTimer = setTimeout(() => pollJob(jobId), 1500);
  } catch (e) {
    ElMessage.error(extractError(e));
    running.value = false;
    stopPolling();
  }
}

async function runWorkflow() {
  running.value = true;
  result.value = null;
  showMarkdown.value = false;
  runProgress.value = 0;
  runMessage.value = "排队中…";
  router.replace({ query: { symbol: symbol.value, timeframe: timeframe.value } });
  try {
    const { data } = await jobsApi.cryptoWorkflow(buildRunPayload());
    await pollJob(data.job_id);
  } catch (e) {
    ElMessage.error(extractError(e));
    running.value = false;
  }
}

onUnmounted(stopPolling);

async function openRun(run_id: string) {
  try {
    const { data } = await cryptoApi.workflowRunGet(run_id);
    result.value = data;
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

function pct(v: unknown) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return (n * 100).toFixed(1) + "%";
}

function fmtPrice(v: unknown) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  if (n >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (n >= 1) return n.toFixed(4);
  return n.toFixed(6);
}

const priceGuidance = computed(() => result.value?.advice?.price_guidance);

function statusTagType(status: string) {
  if (status === "ok") return "success";
  if (status === "skipped") return "info";
  if (status === "error") return "danger";
  return "info";
}

async function copyMarkdown() {
  const md = result.value?.advice?.markdown;
  if (!md) return;
  try {
    await navigator.clipboard.writeText(md);
    ElMessage.success("已复制 Markdown");
  } catch {
    ElMessage.error("复制失败");
  }
}

onMounted(async () => {
  const q = String(route.query.symbol || "").toUpperCase();
  if (q) symbol.value = q;
  const tf = String(route.query.timeframe || "");
  if (tf) timeframe.value = tf;
  loading.value = true;
  try {
    await loadCatalog();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div v-loading="loading">
    <h1 class="page-title">Workflow 分析</h1>
    <p class="page-desc">
      可配置分析流水线：技术面 → qlib ML → 策略信号 → VaR → 期权波动 → 综合投资建议（支持 VaR 风险门控）。
    </p>

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <template #header>模板与步骤</template>
          <el-form label-width="88px" size="small">
            <el-form-item label="模板">
              <el-select v-model="selectedTemplateId" style="width: 100%" @change="onSelectTemplate">
                <el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id!" />
              </el-select>
            </el-form-item>
            <el-form-item label="名称">
              <el-input v-model="templateName" placeholder="模板名称" />
            </el-form-item>
            <el-form-item label="标的">
              <el-select v-model="symbol" style="width: 120px">
                <el-option label="BTC" value="BTC" />
                <el-option label="ETH" value="ETH" />
                <el-option label="SOL" value="SOL" />
                <el-option label="BNB" value="BNB" />
              </el-select>
            </el-form-item>
            <el-form-item label="周期">
              <el-select v-model="timeframe" style="width: 100px">
                <el-option label="1d" value="1d" />
                <el-option label="4h" value="4h" />
                <el-option label="1h" value="1h" />
                <el-option label="15m" value="15m" />
              </el-select>
            </el-form-item>
            <el-form-item label="数据">
              <el-checkbox v-model="refreshOhlcv">运行前刷新 OHLCV</el-checkbox>
            </el-form-item>
          </el-form>

          <el-table :data="sortedSteps" size="small" stripe class="steps-table">
            <el-table-column label="#" width="40">
              <template #default="{ $index }">{{ $index + 1 }}</template>
            </el-table-column>
            <el-table-column label="步骤" min-width="120">
              <template #default="{ row }">
                {{ stepName(row.id) }}
              </template>
            </el-table-column>
            <el-table-column label="启用" width="64">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" size="small" :disabled="row.id === 'advice_synth'" />
              </template>
            </el-table-column>
            <el-table-column label="排序" width="88">
              <template #default="{ $index }">
                <el-button link size="small" :disabled="$index === 0" @click="moveStep($index, -1)">↑</el-button>
                <el-button
                  link
                  size="small"
                  :disabled="$index === sortedSteps.length - 1"
                  @click="moveStep($index, 1)"
                >
                  ↓
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-for="step in sortedSteps" :key="step.id + '-params'" class="step-params">
            <template v-if="step.enabled && step.id === 'zipline_strategy'">
              <p class="param-label">策略信号</p>
              <el-select
                v-model="stepParams(step).strategy_id"
                filterable
                size="small"
                style="width: 220px"
              >
                <el-option v-for="s in tvStrategies" :key="s.id" :label="s.name" :value="s.id" />
              </el-select>
            </template>
            <template v-if="step.enabled && step.id === 'var_symbol'">
              <p class="param-label">VaR 名义 (USDT)</p>
              <el-input-number
                v-model="stepParams(step).notional_usdt"
                :min="100"
                :step="1000"
                size="small"
              />
            </template>
            <template v-if="step.enabled && step.id === 'qlib_ml'">
              <p class="param-label">ML 算法</p>
              <el-select v-model="stepParams(step).algorithm" size="small" style="width: 100px">
                <el-option label="both" value="both" />
                <el-option label="xgb" value="xgb" />
                <el-option label="lgb" value="lgb" />
              </el-select>
              <el-checkbox v-model="stepParams(step).use_cache" size="small">
                复用缓存（数据未变免重训）
              </el-checkbox>
            </template>
            <template v-if="step.enabled && step.id === 'advice_synth'">
              <p class="param-label">建议合成</p>
              VaR 门控
              <el-input-number
                v-model="stepParams(step).var_gate_pct"
                :min="0.02"
                :max="0.2"
                :step="0.01"
                size="small"
              />
              最大仓位
              <el-input-number
                v-model="stepParams(step).max_position_pct"
                :min="0.1"
                :max="1"
                :step="0.05"
                size="small"
              />
              止损σ
              <el-input-number
                v-model="stepParams(step).sl_sigma"
                :min="0.5"
                :max="3"
                :step="0.1"
                size="small"
              />
              止盈σ
              <el-input-number
                v-model="stepParams(step).tp_sigma"
                :min="0.5"
                :max="4"
                :step="0.1"
                size="small"
              />
            </template>
          </div>

          <div class="toolbar mt">
            <el-button size="small" @click="duplicateTemplate">复制模板</el-button>
            <el-button size="small" @click="saveTemplate">保存</el-button>
            <el-button type="primary" :loading="running" @click="runWorkflow">运行</el-button>
          </div>
          <div v-if="running" class="run-progress mt">
            <el-progress :percentage="runProgress" :stroke-width="14" striped striped-flow />
            <p class="muted small">{{ runMessage }}</p>
          </div>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card v-if="result?.advice" shadow="never" class="panel-card advice-card">
          <template #header>
            <span>综合投资建议</span>
            <el-button link type="primary" class="header-btn" @click="copyMarkdown">复制报告</el-button>
            <el-button link class="header-btn" @click="showMarkdown = !showMarkdown">
              {{ showMarkdown ? "隐藏" : "Markdown" }}
            </el-button>
          </template>
          <el-alert
            :title="result.advice.headline"
            :type="result.advice.stance === '看涨' ? 'success' : result.advice.stance === '看跌' ? 'warning' : 'info'"
            :closable="false"
            show-icon
          />
          <div class="advice-metrics mt">
            <el-tag>方向 {{ result.advice.stance }}</el-tag>
            <el-tag type="info">建议仓位 {{ pct(result.advice.suggested_position_pct) }}</el-tag>
            <el-tag :type="result.advice.risk_level === '高' ? 'danger' : 'info'">
              风险 {{ result.advice.risk_level }}
            </el-tag>
            <el-tag v-if="result.advice.signal_agreement" type="info">
              信号 {{ result.advice.signal_agreement }}
            </el-tag>
            <el-tag v-if="result.advice.var_gate_triggered" type="danger">VaR 门控</el-tag>
            <el-tag type="info">置信 {{ pct(result.advice.confidence) }}</el-tag>
          </div>
          <p class="mt">{{ result.advice.advice }}</p>
          <el-card v-if="priceGuidance?.available" shadow="never" class="price-card mt">
            <template #header>IV 参考价位</template>
            <el-descriptions :column="2" size="small" border>
              <el-descriptions-item label="现价">{{ fmtPrice(priceGuidance.spot) }}</el-descriptions-item>
              <el-descriptions-item label="IV 来源">
                {{ priceGuidance.iv_source === "options" ? "期权 ATM" : priceGuidance.iv_source === "realized" ? "历史波动" : "默认" }}
                · {{ pct(priceGuidance.atm_iv) }}
              </el-descriptions-item>
              <el-descriptions-item label="参考买入">
                <strong>{{ fmtPrice(priceGuidance.entry_price) }}</strong>
              </el-descriptions-item>
              <el-descriptions-item label="说明">{{ priceGuidance.entry_note }}</el-descriptions-item>
              <el-descriptions-item label="止损">
                <span class="down">{{ fmtPrice(priceGuidance.stop_loss_price) }}</span>
                <span class="muted small">（{{ pct(priceGuidance.stop_loss_pct) }}）</span>
              </el-descriptions-item>
              <el-descriptions-item label="止盈">
                <span class="up">{{ fmtPrice(priceGuidance.take_profit_price) }}</span>
                <span class="muted small">（{{ pct(priceGuidance.take_profit_pct) }}）</span>
              </el-descriptions-item>
              <el-descriptions-item label="预期波动" :span="2">
                {{ priceGuidance.horizon_days }} 日 · 约 {{ pct(priceGuidance.expected_move_pct) }}
                （{{ fmtPrice(priceGuidance.expected_move_usd) }} USD）
              </el-descriptions-item>
            </el-descriptions>
            <p class="muted small mt">{{ priceGuidance.disclaimer }}</p>
          </el-card>
          <ul class="bullets">
            <li v-for="(b, i) in result.advice.bullets" :key="i">{{ b }}</li>
          </ul>
          <pre v-if="showMarkdown && result.advice.markdown" class="md-preview">{{ result.advice.markdown }}</pre>
          <p class="muted small">{{ result.advice.disclaimer }}</p>
        </el-card>

        <el-card v-if="result" shadow="never" class="panel-card mt">
          <template #header>
            分步结果 · {{ result.symbol }} {{ result.timeframe }}
            <span v-if="result.bars" class="muted small">（{{ result.bars }} bars）</span>
          </template>
          <el-timeline>
            <el-timeline-item
              v-for="step in result.steps"
              :key="step.id"
              :type="step.status === 'error' ? 'danger' : step.status === 'ok' ? 'success' : 'info'"
            >
              <div class="step-row">
                <strong>{{ stepName(step.id) }}</strong>
                <el-tag size="small" :type="statusTagType(step.status)">{{ step.status }}</el-tag>
                <span v-if="step.elapsed_s != null" class="muted small">{{ step.elapsed_s }}s</span>
              </div>
              <p class="step-summary">{{ step.summary || step.error }}</p>
              <el-collapse v-if="step.output && step.status !== 'error'">
                <el-collapse-item title="详情" :name="step.id">
                  <pre class="step-json">{{ JSON.stringify(step.output, null, 2) }}</pre>
                </el-collapse-item>
              </el-collapse>
            </el-timeline-item>
          </el-timeline>
        </el-card>

        <el-card shadow="never" class="panel-card mt">
          <template #header>历史运行</template>
          <el-empty v-if="!runs.length" description="暂无记录" />
          <el-table
            v-else
            :data="runs"
            size="small"
            @row-click="(row: CryptoWorkflowRunSummary) => openRun(row.run_id)"
          >
            <el-table-column prop="generated_at" label="时间" min-width="160" />
            <el-table-column prop="symbol" label="标的" width="72" />
            <el-table-column prop="stance" label="研判" width="72" />
            <el-table-column prop="risk_level" label="风险" width="64" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
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
  margin-bottom: 12px;
}
.mt {
  margin-top: 12px;
}
.muted {
  color: var(--text-muted);
}
.small {
  font-size: 11px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.steps-table {
  margin-top: 8px;
}
.step-params {
  margin-top: 8px;
}
.param-label {
  font-size: 12px;
  color: var(--text-muted);
  margin: 8px 0 4px;
}
.advice-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.bullets {
  margin: 8px 0;
  padding-left: 18px;
  font-size: 13px;
}
.step-json,
.md-preview {
  font-size: 11px;
  max-height: 240px;
  overflow: auto;
  background: var(--el-fill-color-light);
  padding: 8px;
  border-radius: 4px;
  white-space: pre-wrap;
}
.step-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.step-summary {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}
.header-btn {
  float: right;
  margin-left: 8px;
}
.price-card {
  background: var(--el-fill-color-lighter);
}
.down {
  color: var(--el-color-danger);
}
.up {
  color: var(--el-color-success);
}
</style>
