<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  cryptoApi,
  type OptionsIvSkewResult,
  type OptionsTermStructureResult,
  type OptionsAlignedCompareResult,
  type OptionsCommonExpiriesResult,
  type OptionsGreeksResult,
  type OptionsSpreadAlertConfig,
  type OptionsSpreadAlertLogRow,
  type OptionsSpreadHistoryRow,
  type OptionsVenueCompareItem,
  type OptionsVenueCompareScanResult,
  type OptionsVenueTermCompareResult,
  type OptionsVolScanResult,
  type StrikeProbabilityReport,
} from "@/api/crypto";
import { extractError } from "@/api/http";
import { jobsApi } from "@/api/jobs";
import { useRouter } from "vue-router";
import OptionsLineChart from "@/components/options/OptionsLineChart.vue";
import IvSkewChart from "@/components/options/IvSkewChart.vue";
import StrikeProbChart from "@/components/options/StrikeProbChart.vue";
import DualVenueLineChart from "@/components/options/DualVenueLineChart.vue";

const router = useRouter();
const activeTab = ref("scan");
const jobEnqueueing = ref(false);

const loading = ref(false);
const scan = ref<OptionsVolScanResult | null>(null);
const selectedBase = ref("");
const error = ref("");

const strikeLoading = ref(false);
const strikeReport = ref<StrikeProbabilityReport | null>(null);
const strikeError = ref("");
const fullChain = ref(false);
const selectedExpiry = ref("");

const termLoading = ref(false);
const termStructure = ref<OptionsTermStructureResult | null>(null);
const skewLoading = ref(false);
const ivSkew = ref<OptionsIvSkewResult | null>(null);

const compareLoading = ref(false);
const compareScan = ref<OptionsVenueCompareScanResult | null>(null);
const compareTerm = ref<OptionsVenueTermCompareResult | null>(null);
const compareTermLoading = ref(false);
const alignedLoading = ref(false);
const alignedReport = ref<OptionsAlignedCompareResult | null>(null);
const commonExpiries = ref<OptionsCommonExpiriesResult | null>(null);
const alignedExpiryDate = ref("");
const spreadHistory = ref<OptionsSpreadHistoryRow[]>([]);
const spreadHistoryLoading = ref(false);

const greeksLoading = ref(false);
const greeksReport = ref<OptionsGreeksResult | null>(null);
const greeksSide = ref<"call" | "put">("call");

const spreadAlertVisible = ref(false);
const spreadAlertSaving = ref(false);
const spreadAlertTesting = ref(false);
const spreadAlertLog = ref<OptionsSpreadAlertLogRow[]>([]);
const spreadAlertForm = ref<OptionsSpreadAlertConfig>({
  enabled: true,
  elevated_pp: 2.5,
  hot_pp: 5,
  cooldown_minutes: 60,
  symbols: ["BTC", "ETH", "SOL", "BNB"],
  webhook_on_alert: true,
  bark_on_alert: true,
});

const configVisible = ref(false);
const configForm = ref({
  symbols: "BTC,ETH,SOL,BNB",
  lookback_days: 30,
  iv_percentile_threshold: 80,
  iv_change_24h_threshold: 10,
});
const configSaving = ref(false);

const ivHistory = ref<{ ts: string; atm_iv?: number }[]>([]);
const historyLoading = ref(false);

const ivChartPoints = computed(() =>
  ivHistory.value
    .filter((r) => r.atm_iv != null)
    .map((r) => ({
      label: r.ts,
      value: Number(r.atm_iv) * 100,
    })),
);

const termChartPoints = computed(() =>
  (termStructure.value?.points || []).map((p) => ({
    label: `${p.dte?.toFixed(0)}d`,
    value: Number(p.atm_iv) * 100,
  })),
);

const strikeChartRows = computed(() =>
  (strikeReport.value?.rows || []).map((r) => ({
    strike: r.strike,
    model: r.model?.expiry_itm_call,
    implied: r.implied?.expiry_itm_call,
  })),
);

const compareByBase = computed(() => {
  const map: Record<string, OptionsVenueCompareItem> = {};
  for (const item of compareScan.value?.items || []) {
    map[item.base] = item;
  }
  return map;
});

const selectedCompare = () => compareByBase.value[selectedBase.value];

const activeAligned = computed(
  () => alignedReport.value || selectedCompare()?.aligned || null,
);

const alignedChartRows = computed(() =>
  (activeAligned.value?.rows || []).map((r) => ({
    strike: r.strike,
    model: r.binance_iv,
    implied: r.deribit_iv,
  })),
);

const expiryOptions = computed(() => {
  const fromCommon = commonExpiries.value?.expiries || [];
  const fromAligned = activeAligned.value?.common_expiries || [];
  const src = fromCommon.length ? fromCommon : fromAligned;
  return src.map((e) => ({
    value: e.expiry_date,
    label: `${e.expiry_date} · DTE ${e.dte?.toFixed(0)}d · Δ ${e.atm_iv_spread_pp ?? "—"}pp`,
  }));
});

const spreadHistoryChartPoints = computed(() =>
  spreadHistory.value
    .filter((r) => r.iv_spread_pp != null)
    .map((r) => ({
      label: r.ts.slice(5, 16).replace("T", " "),
      value: Number(r.iv_spread_pp),
    })),
);

const venueTermSeries = computed(() => {
  if (!compareTerm.value) return [];
  const bPts = (compareTerm.value.binance.points || []).map((p) => ({
    label: `${p.dte?.toFixed(0)}d`,
    value: Number(p.atm_iv) * 100,
  }));
  const dPts = (compareTerm.value.deribit.points || []).map((p) => ({
    label: `${p.dte?.toFixed(0)}d`,
    value: Number(p.atm_iv) * 100,
  }));
  return [
    { name: "Binance", color: "var(--el-color-primary)", points: bPts },
    { name: "Deribit", color: "var(--el-color-warning)", points: dPts },
  ];
});

const ivAlertLinePct = computed(() => {
  const vals = ivHistory.value.map((r) => r.atm_iv).filter((v): v is number => v != null);
  if (vals.length < 5) return null;
  const sorted = [...vals].sort((a, b) => a - b);
  const pctIdx = scan.value?.config?.iv_percentile_threshold ?? 80;
  const rank = Math.min(sorted.length - 1, Math.floor((pctIdx / 100) * sorted.length));
  return sorted[rank] * 100;
});

function alertTagType(level: string) {
  if (level === "hot") return "danger";
  if (level === "elevated") return "warning";
  return "info";
}

function pct(v: number | null | undefined) {
  if (v == null) return "—";
  return (v * 100).toFixed(1) + "%";
}

function edgeClass(edge: number | null | undefined) {
  if (edge == null) return "";
  if (edge > 0.05) return "edge-pos";
  if (edge < -0.05) return "edge-neg";
  return "";
}

function verdictTagType(verdict: string | undefined) {
  if (verdict === "可考虑买入") return "success";
  if (verdict === "不建议买入") return "danger";
  return "info";
}

function riskTagType(level: string) {
  if (level === "极高" || level === "高") return "danger";
  if (level === "中") return "warning";
  return "info";
}

function selectedAdvice() {
  if (!scan.value || !selectedBase.value) return null;
  return scan.value.advice_pack.advice.find((a) => a.base === selectedBase.value);
}

function selectedRow() {
  return scan.value?.items.find((i) => i.base === selectedBase.value);
}

function selectedStrategies() {
  return selectedRow()?.strategy_pack?.strategies || strikeReport.value?.strategy_pack?.strategies || [];
}

function spreadClass(pp: number | null | undefined) {
  if (pp == null) return "";
  if (Math.abs(pp) >= 5) return "edge-neg";
  if (Math.abs(pp) >= 2.5) return "spread-warn";
  return "";
}

function greekVal(v: number | null | undefined, digits = 4) {
  if (v == null) return "—";
  return Number(v).toFixed(digits);
}

function venueGreeks(row: Record<string, unknown> | null | undefined, venue: "binance" | "deribit") {
  const side = greeksSide.value;
  const leg = (row?.[side] as Record<string, unknown> | undefined)?.[venue] as
    | { greeks?: Record<string, number> }
    | undefined;
  return leg?.greeks;
}

async function loadCompareScan() {
  compareLoading.value = true;
  try {
    const { data } = await cryptoApi.optionsVenueCompare();
    compareScan.value = data as OptionsVenueCompareScanResult;
  } catch {
    compareScan.value = null;
  } finally {
    compareLoading.value = false;
  }
}

async function loadGreeks() {
  if (!selectedBase.value) {
    greeksReport.value = null;
    return;
  }
  greeksLoading.value = true;
  try {
    const { data } = await cryptoApi.optionsGreeks(
      selectedBase.value,
      alignedExpiryDate.value || undefined,
      3,
    );
    greeksReport.value = data;
    if (data.expiry_date && !alignedExpiryDate.value) {
      alignedExpiryDate.value = data.expiry_date;
    }
  } catch {
    greeksReport.value = null;
  } finally {
    greeksLoading.value = false;
  }
}

async function loadSpreadAlertConfig() {
  try {
    const { data } = await cryptoApi.optionsSpreadAlertsConfigGet();
    spreadAlertForm.value = { ...spreadAlertForm.value, ...data };
  } catch {
    /* defaults */
  }
}

async function loadSpreadAlertLog() {
  try {
    const { data } = await cryptoApi.optionsSpreadAlertsLog(20);
    spreadAlertLog.value = data.items || [];
  } catch {
    spreadAlertLog.value = [];
  }
}

async function saveSpreadAlertConfig() {
  spreadAlertSaving.value = true;
  try {
    const { data } = await cryptoApi.optionsSpreadAlertsConfigSave(spreadAlertForm.value);
    spreadAlertForm.value = { ...spreadAlertForm.value, ...data };
    ElMessage.success("价差告警配置已保存");
    spreadAlertVisible.value = false;
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    spreadAlertSaving.value = false;
  }
}

async function testSpreadAlert() {
  spreadAlertTesting.value = true;
  try {
    const { data } = await cryptoApi.optionsSpreadAlertsTest();
    ElMessage.success(data.message || "测试推送已发送");
    await loadSpreadAlertLog();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    spreadAlertTesting.value = false;
  }
}

async function loadSpreadHistory() {
  if (!selectedBase.value) {
    spreadHistory.value = [];
    return;
  }
  spreadHistoryLoading.value = true;
  try {
    const { data } = await cryptoApi.optionsSpreadHistory(selectedBase.value);
    spreadHistory.value = data.items || [];
  } catch {
    spreadHistory.value = [];
  } finally {
    spreadHistoryLoading.value = false;
  }
}

async function loadCompareTerm() {
  if (!selectedBase.value) {
    compareTerm.value = null;
    return;
  }
  compareTermLoading.value = true;
  try {
    const { data } = await cryptoApi.optionsVenueCompareTermStructure(selectedBase.value);
    compareTerm.value = data;
  } catch {
    compareTerm.value = null;
  } finally {
    compareTermLoading.value = false;
  }
}

async function loadCommonExpiries() {
  if (!selectedBase.value) {
    commonExpiries.value = null;
    return;
  }
  try {
    const { data } = await cryptoApi.optionsCommonExpiries(selectedBase.value);
    commonExpiries.value = data;
    if (!alignedExpiryDate.value && data.default_expiry_date) {
      alignedExpiryDate.value = data.default_expiry_date;
    }
  } catch {
    commonExpiries.value = null;
  }
}

async function loadAlignedCompare() {
  if (!selectedBase.value) {
    alignedReport.value = null;
    return;
  }
  const cached = selectedCompare()?.aligned;
  if (
    cached?.available &&
    (!alignedExpiryDate.value || cached.expiry_date === alignedExpiryDate.value) &&
    !alignedReport.value
  ) {
    return;
  }
  alignedLoading.value = true;
  try {
    const { data } = await cryptoApi.optionsAlignedCompare(
      selectedBase.value,
      alignedExpiryDate.value || undefined,
      5,
    );
    alignedReport.value = data;
    if (data.expiry_date) {
      alignedExpiryDate.value = data.expiry_date;
    }
  } catch {
    alignedReport.value = null;
  } finally {
    alignedLoading.value = false;
  }
}

async function loadSurfaceData() {
  if (!selectedBase.value) return;
  termLoading.value = true;
  skewLoading.value = true;
  try {
    const expiry = selectedExpiry.value || selectedRow()?.expiry;
    const [termRes, skewRes] = await Promise.all([
      cryptoApi.optionsTermStructure(selectedBase.value),
      cryptoApi.optionsIvSkew(selectedBase.value, expiry),
    ]);
    termStructure.value = termRes.data;
    ivSkew.value = skewRes.data;
  } catch {
    termStructure.value = null;
    ivSkew.value = null;
  } finally {
    termLoading.value = false;
    skewLoading.value = false;
  }
}

async function loadExpiries() {
  if (!selectedBase.value) return;
  try {
    const { data } = await cryptoApi.optionsExpiries(selectedBase.value);
    if (!selectedExpiry.value && data.default_expiry) {
      selectedExpiry.value = data.default_expiry;
    }
  } catch {
    /* optional */
  }
}

async function loadStrikeProbability() {
  if (!selectedBase.value) {
    strikeReport.value = null;
    return;
  }
  strikeLoading.value = true;
  strikeError.value = "";
  try {
    const row = selectedRow();
    const expiry = selectedExpiry.value || row?.expiry;
    const { data } = await cryptoApi.optionsStrikeProbability(
      selectedBase.value,
      fullChain.value ? 5 : 5,
      expiry,
      {
        iv_alert_level: row?.alert_level,
        iv_percentile: row?.iv_percentile ?? undefined,
        full_chain: fullChain.value,
      },
    );
    strikeReport.value = data;
    if (data.expiry && !selectedExpiry.value) {
      selectedExpiry.value = data.expiry;
    }
  } catch (e) {
    strikeError.value = extractError(e);
    strikeReport.value = null;
  } finally {
    strikeLoading.value = false;
  }
}

async function loadConfig() {
  try {
    const { data } = await cryptoApi.optionsVolConfig();
    configForm.value = {
      symbols: (data.symbols || []).join(","),
      lookback_days: data.lookback_days,
      iv_percentile_threshold: data.iv_percentile_threshold,
      iv_change_24h_threshold: data.iv_change_24h_threshold,
    };
  } catch {
    /* use defaults */
  }
}

async function saveConfig() {
  configSaving.value = true;
  try {
    const symbols = configForm.value.symbols
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    await cryptoApi.optionsVolConfigSave({
      symbols,
      lookback_days: configForm.value.lookback_days,
      iv_percentile_threshold: configForm.value.iv_percentile_threshold,
      iv_change_24h_threshold: configForm.value.iv_change_24h_threshold,
    });
    ElMessage.success("扫描配置已保存");
    configVisible.value = false;
    await runScan();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    configSaving.value = false;
  }
}

async function loadIvHistory() {
  if (!selectedBase.value) {
    ivHistory.value = [];
    return;
  }
  historyLoading.value = true;
  try {
    const { data } = await cryptoApi.optionsVolHistory(selectedBase.value, 60);
    ivHistory.value = [...(data.items || [])].reverse();
  } catch {
    ivHistory.value = [];
  } finally {
    historyLoading.value = false;
  }
}

async function enqueueVolScanJob() {
  jobEnqueueing.value = true;
  try {
    const symbols = configForm.value.symbols
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const { data } = await jobsApi.cryptoOptionsVolScan({
      symbols: symbols.length ? symbols : undefined,
      lookback_days: configForm.value.lookback_days,
    });
    ElMessage.success(`已入队任务 ${data.job_id}`);
    router.push({ name: "tasks" });
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    jobEnqueueing.value = false;
  }
}

async function runScan() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await cryptoApi.optionsVolScan();
    scan.value = data;
    compareScan.value = data.venue_compare_pack || null;
    const first = data.items.find((i) => i.atm_iv != null);
    selectedBase.value = first?.base || data.items[0]?.base || "";
    if (!compareScan.value) {
      await loadCompareScan();
    }
  } catch (e) {
    error.value = extractError(e);
    ElMessage.error(error.value);
  } finally {
    loading.value = false;
  }
}

watch(selectedBase, async () => {
  selectedExpiry.value = "";
  alignedExpiryDate.value = "";
  alignedReport.value = null;
  await loadExpiries();
  loadStrikeProbability();
  loadIvHistory();
  loadSurfaceData();
  loadCompareTerm();
  loadSpreadHistory();
  loadGreeks();
  await loadCommonExpiries();
  await loadAlignedCompare();
});

watch(activeTab, (tab) => {
  if (tab === "venue" && selectedBase.value) {
    loadSpreadHistory();
    loadSpreadAlertLog();
  }
  if (tab === "greeks" && selectedBase.value) {
    loadGreeks();
  }
});

watch(greeksSide, () => {
  /* table re-renders */
});

watch(alignedExpiryDate, () => {
  if (selectedBase.value && alignedExpiryDate.value) {
    alignedReport.value = null;
    loadAlignedCompare();
    loadGreeks();
  }
});

watch([selectedExpiry, fullChain], () => {
  loadStrikeProbability();
  loadSurfaceData();
});

onMounted(async () => {
  await loadConfig();
  await loadSpreadAlertConfig();
  await runScan();
});
</script>

<template>
  <div>
    <h1 class="page-title">期权波动观察</h1>
    <p class="page-desc">
      Binance × Deribit 期权 IV：跨所对比、期限结构、波动偏斜、行权价概率与策略建议（研究用途，非投顾）。
    </p>

    <el-card shadow="never" class="panel-card">
      <div class="toolbar">
        <el-button type="primary" :loading="loading" @click="runScan">立即扫描</el-button>
        <el-button :loading="jobEnqueueing" @click="enqueueVolScanJob">后台任务扫描</el-button>
        <el-button @click="configVisible = true">扫描配置</el-button>
        <span v-if="scan" class="muted mono small">扫描于 {{ scan.scanned_at }}</span>
      </div>

      <el-dialog v-model="spreadAlertVisible" title="跨所 IV 价差告警" width="440px">
        <el-form label-width="130px" size="small">
          <el-form-item label="启用">
            <el-switch v-model="spreadAlertForm.enabled" />
          </el-form-item>
          <el-form-item label="Elevated ≥ pp">
            <el-input-number v-model="spreadAlertForm.elevated_pp" :min="0.5" :max="50" :step="0.5" />
          </el-form-item>
          <el-form-item label="Hot ≥ pp">
            <el-input-number v-model="spreadAlertForm.hot_pp" :min="1" :max="100" :step="0.5" />
          </el-form-item>
          <el-form-item label="冷却(分钟)">
            <el-input-number v-model="spreadAlertForm.cooldown_minutes" :min="1" :max="1440" />
          </el-form-item>
          <el-form-item label="Webhook">
            <el-switch v-model="spreadAlertForm.webhook_on_alert" />
          </el-form-item>
          <el-form-item label="Bark">
            <el-switch v-model="spreadAlertForm.bark_on_alert" />
          </el-form-item>
          <p class="muted small">
            Bark 复用「定时任务告警」中的 Device Key；扫描/定时维护触发跨所对比时自动检测。
          </p>
        </el-form>
        <template #footer>
          <el-button :loading="spreadAlertTesting" @click="testSpreadAlert">测试推送</el-button>
          <el-button @click="spreadAlertVisible = false">取消</el-button>
          <el-button type="primary" :loading="spreadAlertSaving" @click="saveSpreadAlertConfig">
            保存
          </el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="configVisible" title="期权 IV 扫描配置" width="420px">
        <el-form label-width="120px" size="small">
          <el-form-item label="标的列表">
            <el-input v-model="configForm.symbols" placeholder="BTC,ETH,SOL,BNB" />
          </el-form-item>
          <el-form-item label="分位回看(天)">
            <el-input-number v-model="configForm.lookback_days" :min="7" :max="365" />
          </el-form-item>
          <el-form-item label="分位告警≥">
            <el-input-number v-model="configForm.iv_percentile_threshold" :min="50" :max="99" />
          </el-form-item>
          <el-form-item label="24h IV Δ≥%">
            <el-input-number v-model="configForm.iv_change_24h_threshold" :min="1" :max="100" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="configVisible = false">取消</el-button>
          <el-button type="primary" :loading="configSaving" @click="saveConfig">保存</el-button>
        </template>
      </el-dialog>

      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <el-alert
        v-if="compareScan?.overview"
        type="info"
        :closable="false"
        show-icon
        class="mb mt"
        :title="compareScan.overview"
      />

      <el-table
        v-loading="loading || compareLoading"
        :data="scan?.items || []"
        size="small"
        stripe
        highlight-current-row
        class="mt"
        @row-click="(row) => (selectedBase = row.base)"
      >
        <el-table-column prop="rank" label="#" width="48" />
        <el-table-column prop="base" label="标的" width="72" />
        <el-table-column label="Binance IV" width="92">
          <template #default="{ row }">
            {{ row.atm_iv != null ? (row.atm_iv * 100).toFixed(1) + "%" : "—" }}
          </template>
        </el-table-column>
        <el-table-column label="Deribit IV" width="92">
          <template #default="{ row }">
            {{
              compareByBase[row.base]?.deribit?.enabled
                ? (Number(compareByBase[row.base].deribit.atm_iv) * 100).toFixed(1) + "%"
                : "—"
            }}
          </template>
        </el-table-column>
        <el-table-column label="价差" width="80">
          <template #default="{ row }">
            <span :class="spreadClass(compareByBase[row.base]?.comparison?.iv_spread_pp)">
              {{
                compareByBase[row.base]?.comparison?.iv_spread_pp != null
                  ? (compareByBase[row.base].comparison.iv_spread_pp! > 0 ? "+" : "") +
                    compareByBase[row.base].comparison.iv_spread_pp +
                    "pp"
                  : "—"
              }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="IV 分位" width="88">
          <template #default="{ row }">
            {{ row.iv_percentile != null ? row.iv_percentile + "%" : "—" }}
            <el-tag v-if="row.cold_start" size="small" type="info" class="ml">冷启动</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="24h Δ" width="80">
          <template #default="{ row }">
            <span v-if="row.iv_change_24h_pct != null">{{ row.iv_change_24h_pct > 0 ? "+" : "" }}{{ row.iv_change_24h_pct }}%</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="告警" width="90">
          <template #default="{ row }">
            <el-tag :type="alertTagType(row.alert_level || 'normal')" size="small">
              {{ row.alert_level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="策略" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.strategy_pack?.headline || "—" }}
          </template>
        </el-table-column>
        <el-table-column prop="contract" label="合约" min-width="140" show-overflow-tooltip />
      </el-table>
    </el-card>

    <template v-if="scan && selectedBase">
      <div class="sub-toolbar mt">
        <span class="selected-label">已选 <strong>{{ selectedBase }}</strong></span>
        <el-input
          v-model="selectedExpiry"
          placeholder="到期 ISO（可选手动覆盖）"
          size="small"
          class="expiry-input"
          clearable
        />
        <el-switch v-model="fullChain" active-text="完整链" inactive-text="ATM±5" />
      </div>

      <el-tabs v-model="activeTab" class="mt">
        <el-tab-pane label="扫描概览" name="scan">
          <el-row :gutter="16">
            <el-col :span="14">
              <el-card shadow="never" class="panel-card">
                <template #header>投资建议 · {{ selectedBase }}</template>
                <template v-if="selectedAdvice()">
                  <p class="stance">{{ selectedAdvice()!.stance }}</p>
                  <p>{{ selectedAdvice()!.summary }}</p>
                  <ul class="advice-list">
                    <li v-for="(a, i) in selectedAdvice()!.actions" :key="'a' + i">{{ a }}</li>
                  </ul>
                  <el-alert type="warning" :closable="false" show-icon class="mt">
                    <ul class="risk-list">
                      <li v-for="(r, i) in selectedAdvice()!.risks" :key="'r' + i">{{ r }}</li>
                    </ul>
                  </el-alert>
                </template>
                <el-empty v-else description="无建议数据" />
              </el-card>
            </el-col>
            <el-col :span="10">
              <el-card shadow="never" class="panel-card">
                <template #header>合约快照</template>
                <el-descriptions v-if="selectedRow()" :column="1" size="small" border>
                  <el-descriptions-item label="现货/指数">{{ selectedRow()!.underlying_price }}</el-descriptions-item>
                  <el-descriptions-item label="到期">{{ selectedRow()!.expiry }}</el-descriptions-item>
                  <el-descriptions-item label="DTE">{{ selectedRow()!.dte }}</el-descriptions-item>
                  <el-descriptions-item label="行权价">{{ selectedRow()!.strike }}</el-descriptions-item>
                  <el-descriptions-item v-if="selectedRow()!.rank" label="横向排名">
                    #{{ selectedRow()!.rank }}
                  </el-descriptions-item>
                </el-descriptions>
              </el-card>
              <el-card v-loading="historyLoading" shadow="never" class="panel-card mt">
                <template #header>IV 历史趋势</template>
                <OptionsLineChart
                  :points="ivChartPoints"
                  :threshold="ivAlertLinePct"
                  threshold-label="历史高分位参考"
                  :y-format="(v) => v.toFixed(1) + '%'"
                  color="var(--el-color-primary)"
                />
              </el-card>
            </el-col>
          </el-row>
        </el-tab-pane>

        <el-tab-pane label="概率分析" name="prob">
          <el-card v-loading="strikeLoading" shadow="never" class="panel-card">
            <template #header>
              行权价概率 · {{ selectedBase }}
              <span v-if="strikeReport" class="muted small header-meta">
                现货 {{ strikeReport.spot }} · DTE {{ strikeReport.dte?.toFixed(1) }}d
              </span>
            </template>
            <el-alert v-if="strikeError" type="error" :title="strikeError" show-icon class="mb" />
            <el-alert
              v-else-if="strikeReport && !strikeReport.model.enabled"
              type="info"
              :closable="false"
              show-icon
              class="mb"
              :title="strikeReport.model.reason || '模型概率不可用'"
            />
            <StrikeProbChart v-if="strikeChartRows.length" :rows="strikeChartRows" class="mb" />
            <el-table
              v-if="strikeReport?.rows?.length"
              :data="strikeReport.rows"
              size="small"
              stripe
              class="strike-table"
              max-height="420"
            >
              <el-table-column prop="strike" label="行权价" width="88" fixed />
              <el-table-column label="虚值%" width="72">
                <template #default="{ row }">{{ row.moneyness_pct != null ? row.moneyness_pct + "%" : "—" }}</template>
              </el-table-column>
              <el-table-column label="Mark IV" width="76">
                <template #default="{ row }">{{ row.mark_iv != null ? (row.mark_iv * 100).toFixed(1) + "%" : "—" }}</template>
              </el-table-column>
              <el-table-column label="Call 模型/隐含" min-width="120">
                <template #default="{ row }">{{ pct(row.model?.expiry_itm_call) }} / {{ pct(row.implied?.expiry_itm_call) }}</template>
              </el-table-column>
              <el-table-column label="Put 模型/隐含" min-width="120">
                <template #default="{ row }">{{ pct(row.model?.expiry_itm_put) }} / {{ pct(row.implied?.expiry_itm_put) }}</template>
              </el-table-column>
              <el-table-column label="Δ Call" width="80">
                <template #default="{ row }">
                  <span :class="edgeClass(row.edge_expiry)">
                    {{ row.edge_expiry != null ? (row.edge_expiry > 0 ? "+" : "") + (row.edge_expiry * 100).toFixed(1) + "pp" : "—" }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="Δ Put" width="80">
                <template #default="{ row }">
                  <span :class="edgeClass(row.edge_expiry_put)">
                    {{ row.edge_expiry_put != null ? (row.edge_expiry_put > 0 ? "+" : "") + (row.edge_expiry_put * 100).toFixed(1) + "pp" : "—" }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="买 Call" width="96">
                <template #default="{ row }">
                  <el-tag v-if="row.purchase?.verdict" :type="verdictTagType(row.purchase.verdict)" size="small">
                    {{ row.purchase.verdict }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="买 Put" width="96">
                <template #default="{ row }">
                  <el-tag
                    v-if="row.purchase_put?.verdict"
                    :type="verdictTagType(row.purchase_put.verdict)"
                    size="small"
                  >
                    {{ row.purchase_put.verdict }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else-if="!strikeLoading && !strikeError" description="无行权价数据" />
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="波动曲面" name="surface">
          <el-row :gutter="16">
            <el-col :span="12">
              <el-card v-loading="termLoading" shadow="never" class="panel-card">
                <template #header>
                  期限结构
                  <span v-if="termStructure?.slope_note" class="muted small header-meta">{{ termStructure.slope_note }}</span>
                </template>
                <OptionsLineChart
                  :points="termChartPoints"
                  :y-format="(v) => v.toFixed(1) + '%'"
                  color="var(--el-color-success)"
                />
              </el-card>
            </el-col>
            <el-col :span="12">
              <el-card v-loading="skewLoading" shadow="never" class="panel-card">
                <template #header>
                  波动率偏斜
                  <span v-if="ivSkew?.skew_25d_proxy != null" class="muted small header-meta">
                    偏斜代理 {{ (ivSkew.skew_25d_proxy * 100).toFixed(1) }}pp
                  </span>
                </template>
                <IvSkewChart :points="ivSkew?.points || []" :spot="ivSkew?.spot" />
              </el-card>
            </el-col>
          </el-row>
        </el-tab-pane>

        <el-tab-pane label="Greeks" name="greeks">
          <el-card v-loading="greeksLoading" shadow="never" class="panel-card">
            <template #header>
              期权 Greeks · {{ selectedBase }}
              <el-radio-group v-model="greeksSide" size="small" class="ml">
                <el-radio-button value="call">Call</el-radio-button>
                <el-radio-button value="put">Put</el-radio-button>
              </el-radio-group>
              <el-button size="small" class="ml" :loading="greeksLoading" @click="loadGreeks">
                刷新
              </el-button>
            </template>
            <p v-if="greeksReport?.available" class="muted small mb">
              到期 {{ greeksReport.expiry_date }} · DTE {{ greeksReport.dte }}d · ATM
              {{ greeksReport.atm_strike }}
            </p>
            <el-table
              v-if="greeksReport?.rows?.length"
              :data="greeksReport.rows"
              size="small"
              stripe
              max-height="480"
            >
              <el-table-column prop="strike" label="行权价" width="88" fixed />
              <el-table-column label="虚值%" width="72">
                <template #default="{ row }">
                  {{ row.moneyness_pct != null ? row.moneyness_pct + "%" : "—" }}
                </template>
              </el-table-column>
              <el-table-column label="B Δ" width="72">
                <template #default="{ row }">{{ greekVal(venueGreeks(row, "binance")?.delta) }}</template>
              </el-table-column>
              <el-table-column label="B Γ" width="80">
                <template #default="{ row }">{{ greekVal(venueGreeks(row, "binance")?.gamma, 6) }}</template>
              </el-table-column>
              <el-table-column label="B Θ" width="80">
                <template #default="{ row }">{{ greekVal(venueGreeks(row, "binance")?.theta, 2) }}</template>
              </el-table-column>
              <el-table-column label="B V" width="80">
                <template #default="{ row }">{{ greekVal(venueGreeks(row, "binance")?.vega, 2) }}</template>
              </el-table-column>
              <el-table-column label="D Δ" width="72">
                <template #default="{ row }">{{ greekVal(venueGreeks(row, "deribit")?.delta) }}</template>
              </el-table-column>
              <el-table-column label="D Γ" width="80">
                <template #default="{ row }">{{ greekVal(venueGreeks(row, "deribit")?.gamma, 6) }}</template>
              </el-table-column>
              <el-table-column label="D Θ" width="80">
                <template #default="{ row }">{{ greekVal(venueGreeks(row, "deribit")?.theta, 2) }}</template>
              </el-table-column>
              <el-table-column label="D V" width="80">
                <template #default="{ row }">{{ greekVal(venueGreeks(row, "deribit")?.vega, 2) }}</template>
              </el-table-column>
            </el-table>
            <el-empty
              v-else
              :description="greeksReport?.reason || '暂无 Greeks 数据'"
            />
            <p v-if="greeksReport?.disclaimer" class="disclaimer muted small mt">
              {{ greeksReport.disclaimer }}
            </p>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="跨所对比" name="venue">
          <el-card v-loading="alignedLoading" shadow="never" class="panel-card">
            <template #header>
              同到期对齐 · {{ selectedBase }}
              <el-button size="small" class="ml" @click="spreadAlertVisible = true">
                价差告警
              </el-button>
              <el-tag v-if="activeAligned?.available" size="small" type="success" class="ml">
                已对齐
              </el-tag>
            </template>
            <div class="sub-toolbar mb">
              <span class="muted small">共同到期日</span>
              <el-select
                v-model="alignedExpiryDate"
                placeholder="选择到期日"
                size="small"
                class="expiry-select"
                :disabled="!expiryOptions.length"
              >
                <el-option
                  v-for="opt in expiryOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
              <el-button size="small" :loading="alignedLoading" @click="loadAlignedCompare">
                刷新对齐
              </el-button>
            </div>
            <template v-if="activeAligned?.available">
              <p class="compare-summary">{{ activeAligned.comparison?.summary }}</p>
              <el-descriptions :column="4" size="small" border class="mt">
                <el-descriptions-item label="到期日">
                  {{ activeAligned.expiry_date }}
                </el-descriptions-item>
                <el-descriptions-item label="DTE">
                  {{ activeAligned.dte }}
                </el-descriptions-item>
                <el-descriptions-item label="ATM 价差">
                  <span :class="spreadClass(activeAligned.comparison?.iv_spread_pp)">
                    {{ activeAligned.comparison?.iv_spread_pp }} pp
                  </span>
                </el-descriptions-item>
                <el-descriptions-item label="行权价带宽">
                  {{ activeAligned.comparison?.strike_spread_range_pp ?? "—" }} pp
                </el-descriptions-item>
              </el-descriptions>
              <el-row :gutter="16" class="mt">
                <el-col :span="12">
                  <p class="muted small">Binance · {{ activeAligned.atm?.binance_symbol }}</p>
                  <p>ATM {{ activeAligned.atm_strike }} · IV {{ pct(activeAligned.atm?.binance_iv) }}</p>
                </el-col>
                <el-col :span="12">
                  <p class="muted small">Deribit · {{ activeAligned.atm?.deribit_symbol }}</p>
                  <p>ATM {{ activeAligned.atm_strike }} · IV {{ pct(activeAligned.atm?.deribit_iv) }}</p>
                </el-col>
              </el-row>
              <StrikeProbChart v-if="alignedChartRows.length" :rows="alignedChartRows" class="mt mb" />
              <el-table :data="activeAligned.rows || []" size="small" stripe max-height="360">
                <el-table-column prop="strike" label="行权价" width="88" />
                <el-table-column label="虚值%" width="72">
                  <template #default="{ row }">
                    {{ row.moneyness_pct != null ? row.moneyness_pct + "%" : "—" }}
                  </template>
                </el-table-column>
                <el-table-column label="Binance IV" width="96">
                  <template #default="{ row }">{{ pct(row.binance_iv) }}</template>
                </el-table-column>
                <el-table-column label="Deribit IV" width="96">
                  <template #default="{ row }">{{ pct(row.deribit_iv) }}</template>
                </el-table-column>
                <el-table-column label="价差 B−D" width="88">
                  <template #default="{ row }">
                    <span :class="spreadClass(row.iv_spread_pp)">
                      {{ row.iv_spread_pp > 0 ? "+" : "" }}{{ row.iv_spread_pp }}pp
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="binance_symbol" label="B 合约" min-width="140" show-overflow-tooltip />
                <el-table-column prop="deribit_symbol" label="D 合约" min-width="140" show-overflow-tooltip />
              </el-table>
              <p
                v-if="selectedCompare()?.comparison?.near_month_summary"
                class="muted small mt near-month-note"
              >
                近月独立选约：{{ selectedCompare()!.comparison.near_month_summary }}
              </p>
            </template>
            <el-empty v-else :description="activeAligned?.reason || '无共同到期合约'" />
          </el-card>
          <el-card v-loading="spreadHistoryLoading" shadow="never" class="panel-card mt">
            <template #header>
              对齐价差历史 · {{ selectedBase }}
              <span v-if="spreadHistory.length" class="muted small header-meta">
                {{ spreadHistory.length }} 条快照
              </span>
            </template>
            <OptionsLineChart
              v-if="spreadHistoryChartPoints.length"
              :points="spreadHistoryChartPoints"
              :y-format="(v) => (v > 0 ? '+' : '') + v.toFixed(1) + 'pp'"
              color="var(--el-color-danger)"
            />
            <el-empty v-else description="暂无价差历史（扫描或定时任务后会自动记录）" />
          </el-card>
          <el-card v-if="spreadAlertLog.length" shadow="never" class="panel-card mt">
            <template #header>最近价差告警</template>
            <el-table :data="spreadAlertLog" size="small" stripe max-height="200">
              <el-table-column prop="ts" label="时间" width="160" show-overflow-tooltip />
              <el-table-column prop="base" label="标的" width="64" />
              <el-table-column prop="level" label="级别" width="72">
                <template #default="{ row }">
                  <el-tag :type="row.level === 'hot' ? 'danger' : 'warning'" size="small">
                    {{ row.level }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="message" label="说明" min-width="240" show-overflow-tooltip />
            </el-table>
          </el-card>
          <el-card v-loading="compareTermLoading" shadow="never" class="panel-card mt">
            <template #header>期限结构对比（ATM IV）</template>
            <DualVenueLineChart :series="venueTermSeries" />
          </el-card>
          <el-table
            v-if="compareScan?.items?.length"
            :data="compareScan.items"
            size="small"
            stripe
            class="mt panel-card"
          >
            <el-table-column prop="base" label="标的" width="72" />
            <el-table-column label="Binance" width="88">
              <template #default="{ row }">{{ pct(row.binance?.atm_iv) }}</template>
            </el-table-column>
            <el-table-column label="Deribit" width="88">
              <template #default="{ row }">{{ pct(row.deribit?.atm_iv) }}</template>
            </el-table-column>
            <el-table-column label="到期" width="100">
              <template #default="{ row }">
                {{ row.comparison?.expiry_date || row.aligned?.expiry_date || "—" }}
              </template>
            </el-table-column>
            <el-table-column label="价差" width="80">
              <template #default="{ row }">
                <span :class="spreadClass(row.comparison?.iv_spread_pp)">
                  {{ row.comparison?.iv_spread_pp != null ? row.comparison.iv_spread_pp + "pp" : "—" }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="模式" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.comparison?.mode === 'aligned_expiry' ? 'success' : 'info'">
                  {{ row.comparison?.mode === "aligned_expiry" ? "同到期" : "近月" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="说明" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.comparison?.summary }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="策略建议" name="strategy">
          <el-card shadow="never" class="panel-card">
            <template #header>推荐策略框架 · {{ selectedBase }}</template>
            <el-empty v-if="!selectedStrategies().length" description="暂无策略建议" />
            <div v-for="(s, i) in selectedStrategies()" :key="i" class="strategy-card">
              <div class="strategy-head">
                <span class="strategy-name">{{ s.name }}</span>
                <el-tag :type="riskTagType(s.risk_level)" size="small">{{ s.risk_level }}风险</el-tag>
                <span class="muted small">评分 {{ (s.score * 100).toFixed(0) }}</span>
              </div>
              <p class="strategy-rationale">{{ s.rationale }}</p>
              <el-table v-if="s.legs?.length" :data="s.legs" size="small" class="mt">
                <el-table-column prop="side" label="方向" width="64" />
                <el-table-column prop="type" label="类型" width="64" />
                <el-table-column prop="strike" label="行权价" width="100" />
                <el-table-column prop="symbol" label="合约" min-width="140" show-overflow-tooltip />
              </el-table>
            </div>
            <p class="disclaimer muted small mt">
              {{ selectedRow()?.strategy_pack?.disclaimer || strikeReport?.strategy_pack?.disclaimer }}
            </p>
          </el-card>
        </el-tab-pane>
      </el-tabs>
    </template>

    <p v-if="scan" class="overview muted">{{ scan.advice_pack.overview }}</p>
  </div>
</template>

<style scoped>
.toolbar,
.sub-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.selected-label {
  font-size: 14px;
}
.expiry-input {
  width: 280px;
}
.expiry-select {
  width: 320px;
}
.near-month-note {
  line-height: 1.4;
}
.ml {
  margin-left: 8px;
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
.ml {
  margin-left: 4px;
}
.header-meta {
  margin-left: 8px;
  font-weight: normal;
}
.stance {
  font-weight: 600;
  font-size: 1.05rem;
  margin: 0 0 8px;
}
.advice-list,
.risk-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.5;
}
.overview {
  margin-top: 16px;
}
.disclaimer {
  margin-top: 12px;
  line-height: 1.4;
}
.edge-pos {
  color: var(--el-color-success);
}
.edge-neg {
  color: var(--el-color-danger);
}
.spread-warn {
  color: var(--el-color-warning);
}
.compare-summary {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
}
.strategy-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
}
.strategy-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.strategy-name {
  font-weight: 600;
  font-size: 15px;
}
.strategy-rationale {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
}
</style>
