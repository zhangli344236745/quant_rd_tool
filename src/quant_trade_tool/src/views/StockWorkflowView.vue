<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  stocksApi,
  type StockWorkflowRunResult,
  type StockWorkflowRunSummary,
  type StockWorkflowStepConfig,
  type StockWorkflowStepDef,
  type StockWorkflowTemplate,
} from "@/api/stocks";
import { extractError } from "@/api/http";
import { jobsApi } from "@/api/jobs";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const running = ref(false);
const stepCatalog = ref<StockWorkflowStepDef[]>([]);
const templates = ref<StockWorkflowTemplate[]>([]);
const strategies = ref<Array<{ id: string; name: string; category?: string }>>([]);
const runs = ref<StockWorkflowRunSummary[]>([]);
const result = ref<StockWorkflowRunResult | null>(null);

const selectedTemplateId = ref("");
const templateName = ref("");
const symbol = ref("600519");
const refreshOhlcv = ref(true);
const editSteps = ref<StockWorkflowStepConfig[]>([]);
const showMarkdown = ref(false);
const runProgress = ref(0);
const runMessage = ref("");
let pollTimer: ReturnType<typeof setTimeout> | null = null;

const sortedSteps = computed(() => [...editSteps.value].sort((a, b) => a.order - b.order));
const priceGuidance = computed(() => result.value?.advice?.price_guidance);
const announcementHighImpact = computed(() =>
  (result.value?.advice?.bullets || []).some((b) => String(b).includes("公告门控")),
);

function stepName(id: string) {
  return stepCatalog.value.find((s) => s.id === id)?.name || id;
}

function loadTemplateIntoEditor(tpl: StockWorkflowTemplate) {
  selectedTemplateId.value = tpl.id || "";
  templateName.value = tpl.name || "";
  symbol.value = tpl.symbol_default || "600519";
  editSteps.value = (tpl.steps || []).map((s, i) => ({
    id: s.id,
    enabled: s.enabled !== false,
    order: s.order ?? i,
    params: { ...(s.params || {}) },
  }));
}

async function loadCatalog() {
  const [{ data: steps }, { data: tpls }, { data: strat }, { data: runList }] = await Promise.all([
    stocksApi.workflowSteps(),
    stocksApi.workflowTemplates(),
    stocksApi.ziplineStrategies(),
    stocksApi.workflowRuns(),
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

function stepParams(step: StockWorkflowStepConfig): Record<string, unknown> {
  return step.params;
}

function ensureParam(step: StockWorkflowStepConfig, key: string, fallback: unknown) {
  if (stepParams(step)[key] === undefined) {
    stepParams(step)[key] = fallback;
  }
}

async function saveTemplate() {
  const body: StockWorkflowTemplate = {
    id: selectedTemplateId.value || undefined,
    name: templateName.value || "自定义 Workflow",
    symbol_default: symbol.value,
    timeframe: "1d",
    steps: sortedSteps.value.map((s, i) => ({ ...s, order: i })),
  };
  loading.value = true;
  try {
    const { data } = await stocksApi.workflowTemplateSave(body);
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
    const { data } = await stocksApi.workflowTemplateDuplicate(selectedTemplateId.value);
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
    if (step.id === "var_symbol") ensureParam(step, "notional_cny", 100_000);
    if (step.id === "qlib_ml") {
      ensureParam(step, "algorithm", "both");
      ensureParam(step, "use_cache", true);
    }
    if (step.id === "announcement_scan") {
      ensureParam(step, "min_score", 40);
      ensureParam(step, "notice_limit", 15);
      ensureParam(step, "refresh", true);
      ensureParam(step, "persist", true);
      ensureParam(step, "high_impact_min", 70);
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
    symbol: symbol.value.trim(),
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
        const { data } = await stocksApi.workflowRunGet(runId);
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
  router.replace({ query: { symbol: symbol.value } });
  try {
    const { data } = await jobsApi.stockWorkflow(buildRunPayload());
    await pollJob(data.job_id);
  } catch (e) {
    ElMessage.error(extractError(e));
    running.value = false;
  }
}

onUnmounted(stopPolling);

async function openRun(run_id: string) {
  try {
    const { data } = await stocksApi.workflowRunGet(run_id);
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
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function stanceAlertType(stance: string | undefined) {
  if (stance === "偏多") return "success";
  if (stance === "谨慎") return "warning";
  return "info";
}

function statusTagType(status: string) {
  if (status === "ok") return "success";
  if (status === "skipped") return "info";
  if (status === "error") return "danger";
  return "info";
}

function stepOosSummary(step: { output?: Record<string, unknown> }) {
  return step.output?.oos_summary as
    | { gate_passed?: boolean; test_ic?: number; direction_accuracy?: number; headline?: string }
    | undefined;
}

function stepOosMarkdown(step: { output?: Record<string, unknown> }) {
  return step.output?.oos_markdown as string | undefined;
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
  const q = String(route.query.symbol || "").trim();
  if (q) symbol.value = q;
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
    <h1 class="page-title">A股 Workflow 分析</h1>
    <p class="page-desc">
      可配置分析流水线：技术面 → 公告扫描 → qlib ML → 策略信号 → VaR → 综合投资建议（支持 VaR / 公告风险门控）。
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
              <el-input v-model="symbol" placeholder="如 600519" style="width: 140px" />
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
              <template #default="{ row }">{{ stepName(row.id) }}</template>
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
              <el-select v-model="stepParams(step).strategy_id" filterable size="small" style="width: 220px">
                <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
              </el-select>
            </template>
            <template v-if="step.enabled && step.id === 'var_symbol'">
              <p class="param-label">VaR 名义 (CNY)</p>
              <el-input-number v-model="stepParams(step).notional_cny" :min="1000" :step="10000" size="small" />
            </template>
            <template v-if="step.enabled && step.id === 'qlib_ml'">
              <p class="param-label">ML 算法</p>
              <el-select v-model="stepParams(step).algorithm" size="small" style="width: 100px">
                <el-option label="both" value="both" />
                <el-option label="xgb" value="xgb" />
                <el-option label="lgb" value="lgb" />
              </el-select>
              <el-checkbox v-model="stepParams(step).use_cache" size="small">复用缓存</el-checkbox>
            </template>
            <template v-if="step.enabled && step.id === 'announcement_scan'">
              <p class="param-label">公告扫描</p>
              最低分数
              <el-input-number v-model="stepParams(step).min_score" :min="0" :max="100" size="small" />
              条数
              <el-input-number v-model="stepParams(step).notice_limit" :min="5" :max="30" size="small" />
              高影响阈值
              <el-input-number v-model="stepParams(step).high_impact_min" :min="40" :max="100" size="small" />
              <el-checkbox v-model="stepParams(step).refresh" size="small">实时拉取</el-checkbox>
              <el-checkbox v-model="stepParams(step).persist" size="small">写入雷达库</el-checkbox>
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
            :type="stanceAlertType(result.advice.stance)"
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
            <el-tag v-if="announcementHighImpact" type="warning">公告门控</el-tag>
            <el-tag type="info">置信 {{ pct(result.advice.confidence) }}</el-tag>
            <el-tag v-if="result.audit_record?.run_id" type="info">
              审计 {{ String(result.audit_record.run_id).slice(0, 8) }}
            </el-tag>
          </div>
          <p class="mt">{{ result.advice.advice }}</p>
          <el-card v-if="priceGuidance?.available" shadow="never" class="price-card mt">
            <template #header>参考价位</template>
            <el-descriptions :column="2" size="small" border>
              <el-descriptions-item label="现价">{{ fmtPrice(priceGuidance.spot) }}</el-descriptions-item>
              <el-descriptions-item label="波动来源">
                {{ priceGuidance.iv_source === "realized" ? "历史波动" : "默认" }}
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
            分步结果 · {{ result.symbol }}
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
                <el-tag
                  v-if="stepOosSummary(step)?.gate_passed === true"
                  size="small"
                  type="success"
                >
                  OOS 通过
                </el-tag>
                <el-tag
                  v-else-if="stepOosSummary(step)?.gate_passed === false"
                  size="small"
                  type="warning"
                >
                  OOS 未通过
                </el-tag>
                <span v-if="step.elapsed_s != null" class="muted small">{{ step.elapsed_s }}s</span>
              </div>
              <p class="step-summary">{{ step.summary || step.error }}</p>
              <p v-if="stepOosSummary(step)?.headline" class="muted small">
                {{ stepOosSummary(step)?.headline }}
              </p>
              <el-collapse v-if="stepOosMarkdown(step)" class="step-oos">
                <el-collapse-item title="OOS 协议报告" :name="`${step.id}-oos`">
                  <pre class="oos-md">{{ stepOosMarkdown(step) }}</pre>
                </el-collapse-item>
              </el-collapse>
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
            @row-click="(row: StockWorkflowRunSummary) => openRun(row.run_id)"
          >
            <el-table-column prop="generated_at" label="时间" min-width="160" />
            <el-table-column prop="symbol" label="标的" width="90" />
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
.step-oos {
  margin-top: 8px;
}
.oos-md {
  font-size: 12px;
  white-space: pre-wrap;
  margin: 0;
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
