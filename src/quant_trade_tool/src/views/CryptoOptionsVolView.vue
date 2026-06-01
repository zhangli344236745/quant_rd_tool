<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  cryptoApi,
  type OptionsVolScanResult,
  type StrikeProbabilityReport,
} from "@/api/crypto";
import { extractError } from "@/api/http";

const loading = ref(false);
const scan = ref<OptionsVolScanResult | null>(null);
const selectedBase = ref("");
const error = ref("");

const strikeLoading = ref(false);
const strikeReport = ref<StrikeProbabilityReport | null>(null);
const strikeError = ref("");

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

function selectedAdvice() {
  if (!scan.value || !selectedBase.value) return null;
  return scan.value.advice_pack.advice.find((a) => a.base === selectedBase.value);
}

function selectedRow() {
  return scan.value?.items.find((i) => i.base === selectedBase.value);
}

async function loadStrikeProbability() {
  if (!selectedBase.value) {
    strikeReport.value = null;
    return;
  }
  strikeLoading.value = true;
  strikeError.value = "";
  try {
    const expiry = selectedRow()?.expiry;
    const { data } = await cryptoApi.optionsStrikeProbability(
      selectedBase.value,
      5,
      expiry,
    );
    strikeReport.value = data;
  } catch (e) {
    strikeError.value = extractError(e);
    strikeReport.value = null;
  } finally {
    strikeLoading.value = false;
  }
}

async function runScan() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await cryptoApi.optionsVolScan();
    scan.value = data;
    const first = data.items.find((i) => i.atm_iv != null);
    selectedBase.value = first?.base || data.items[0]?.base || "";
  } catch (e) {
    error.value = extractError(e);
    ElMessage.error(error.value);
  } finally {
    loading.value = false;
  }
}

watch(selectedBase, () => {
  loadStrikeProbability();
});

onMounted(runScan);
</script>

<template>
  <div>
    <h1 class="page-title">期权波动观察</h1>
    <p class="page-desc">
      Binance 近月 ATM 隐含波动率：IV 分位、24h 变化与横向排名；附研究性操作建议（非投顾）。
    </p>

    <el-card shadow="never" class="panel-card">
      <div class="toolbar">
        <el-button type="primary" :loading="loading" @click="runScan">立即扫描</el-button>
        <span v-if="scan" class="muted mono small">扫描于 {{ scan.scanned_at }}</span>
      </div>
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <el-table
        v-loading="loading"
        :data="scan?.items || []"
        size="small"
        stripe
        highlight-current-row
        class="mt"
        @row-click="(row) => (selectedBase = row.base)"
      >
        <el-table-column prop="rank" label="#" width="48" />
        <el-table-column prop="base" label="标的" width="72" />
        <el-table-column label="ATM IV" width="88">
          <template #default="{ row }">
            {{ row.atm_iv != null ? (row.atm_iv * 100).toFixed(1) + "%" : "—" }}
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
        <el-table-column prop="contract" label="合约" min-width="160" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-row v-if="scan && selectedBase" :gutter="16" class="mt">
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
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <el-card
      v-if="scan && selectedBase"
      v-loading="strikeLoading"
      shadow="never"
      class="panel-card mt"
    >
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
        :title="strikeReport.model.reason || '模型概率不可用（缺 OHLCV 或 qlib 样本）'"
      />
      <el-table
        v-if="strikeReport?.rows?.length"
        :data="strikeReport.rows"
        size="small"
        stripe
        class="strike-table"
      >
        <el-table-column prop="strike" label="行权价" width="88" />
        <el-table-column label="虚值%" width="72">
          <template #default="{ row }">
            {{ row.moneyness_pct != null ? row.moneyness_pct + "%" : "—" }}
          </template>
        </el-table-column>
        <el-table-column label="Mark IV" width="80">
          <template #default="{ row }">
            {{ row.mark_iv != null ? (row.mark_iv * 100).toFixed(1) + "%" : "—" }}
          </template>
        </el-table-column>
        <el-table-column label="模型 P(到期≥K)" min-width="110">
          <template #default="{ row }">{{ pct(row.model?.expiry_itm_call) }}</template>
        </el-table-column>
        <el-table-column label="隐含 P(到期≥K)" min-width="110">
          <template #default="{ row }">{{ pct(row.implied?.expiry_itm_call) }}</template>
        </el-table-column>
        <el-table-column label="模型 P(触达≥K)" min-width="110">
          <template #default="{ row }">{{ pct(row.model?.touch_call) }}</template>
        </el-table-column>
        <el-table-column label="Δ 模型−隐含" width="100">
          <template #default="{ row }">
            <span :class="edgeClass(row.edge_expiry)">
              {{
                row.edge_expiry != null
                  ? (row.edge_expiry > 0 ? "+" : "") + (row.edge_expiry * 100).toFixed(1) + "pp"
                  : "—"
              }}
            </span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else-if="!strikeLoading && !strikeError" description="无行权价数据" />
      <p v-if="strikeReport?.disclaimer" class="disclaimer muted small">
        {{ strikeReport.disclaimer }}
      </p>
    </el-card>

    <p v-if="scan" class="overview muted">{{ scan.advice_pack.overview }}</p>
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
</style>
