<script setup lang="ts">
import { computed } from "vue";
import type { OptionsPortfolioGreeksResult } from "@/api/crypto";

const props = defineProps<{
  report: OptionsPortfolioGreeksResult | null;
  loading?: boolean;
  compact?: boolean;
}>();

const summary = computed(() => props.report?.summary);
const legs = computed(() => props.report?.legs || []);
const constituents = computed(() =>
  (props.report?.constituents || []).filter((c) => c.available),
);
const isMulti = computed(() => Boolean(props.report?.multi));

function riskTagType(level: string | undefined) {
  if (level === "高") return "danger";
  if (level === "中") return "warning";
  return "success";
}

function greekVal(v: number | null | undefined, digits = 4) {
  if (v == null) return "—";
  return Number(v).toFixed(digits);
}

function usd(v: number | null | undefined) {
  if (v == null) return "—";
  const sign = v >= 0 ? "" : "-";
  return sign + "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function pct(v: number | null | undefined) {
  if (v == null) return "—";
  return v.toFixed(1) + "%";
}
</script>

<template>
  <div v-loading="loading" class="portfolio-greeks">
    <template v-if="report?.available && summary">
      <div class="head-row">
        <el-tag :type="riskTagType(summary.risk_level)" size="small">
          风险 {{ summary.risk_level }}
        </el-tag>
        <el-tag v-if="report.scale_mode" size="small" type="info">
          {{ report.scale_mode === "margin" ? "保证金缩放" : "名义比例" }}
        </el-tag>
        <span v-if="isMulti && report.bases?.length" class="muted small">
          多币种 · {{ report.bases.join(" / ") }}
        </span>
        <span v-else-if="report.source?.name || report.source?.overlay_id" class="muted small">
          {{ report.source?.name || report.source?.overlay_id }}
        </span>
        <span v-if="!isMulti && report.expiry_date" class="muted small">
          · {{ report.expiry_date }} · DTE {{ report.dte }}d
        </span>
      </div>

      <el-row :gutter="12" class="metric-row">
        <el-col :xs="12" :sm="6">
          <div class="metric-card">
            <div class="metric-label">{{ isMulti ? "净 Δ（USD）" : "净 Δ（币）" }}</div>
            <div class="metric-value">
              {{ isMulti ? usd(summary.delta_usd) : greekVal(summary.delta_coins) }}
            </div>
            <div v-if="!isMulti" class="metric-sub muted small">{{ usd(summary.delta_usd) }}</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="metric-card">
            <div class="metric-label">净 Γ</div>
            <div class="metric-value">{{ greekVal(summary.net?.gamma, 6) }}</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="metric-card">
            <div class="metric-label">净 Θ（日）</div>
            <div class="metric-value">{{ greekVal(summary.net?.theta, 2) }}</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="metric-card">
            <div class="metric-label">净 V</div>
            <div class="metric-value">{{ greekVal(summary.net?.vega, 2) }}</div>
          </div>
        </el-col>
      </el-row>

      <div
        v-if="summary.margin_used_usd != null && !compact"
        class="hedge-hint muted small"
      >
        估算保证金 {{ usd(summary.margin_used_usd) }}
        <span v-if="summary.margin_utilization_pct != null">
          · 占用 {{ pct(summary.margin_utilization_pct) }}
        </span>
      </div>

      <el-row v-if="!compact && !isMulti && summary.scenarios" :gutter="12" class="scenario-row">
        <el-col :span="8">
          <div class="scenario-card muted small">
            现货 +5% 近似 PnL
            <strong>{{ usd(summary.scenarios?.spot_up_5pct_pnl) }}</strong>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="scenario-card muted small">
            1 日 Theta
            <strong>{{ usd(summary.scenarios?.theta_1d_pnl) }}</strong>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="scenario-card muted small">
            IV +1pt
            <strong>{{ usd(summary.scenarios?.iv_up_1pt_pnl) }}</strong>
          </div>
        </el-col>
      </el-row>

      <div
        v-if="summary.hedge_coins != null && !compact && !isMulti"
        class="hedge-hint muted small"
      >
        近似 Delta 对冲：{{ greekVal(summary.hedge_coins) }} 币
        <span v-if="summary.delta_notional_pct != null">
          · 名义敞口 {{ summary.delta_notional_pct }}%
        </span>
      </div>

      <el-alert
        v-for="(msg, i) in summary.alerts || []"
        :key="i"
        :title="msg"
        type="warning"
        show-icon
        :closable="false"
        class="alert-item"
      />

      <el-table
        v-if="constituents.length && !compact"
        :data="constituents"
        size="small"
        stripe
        class="legs-table"
        max-height="200"
      >
        <el-table-column prop="base" label="币种" width="72" />
        <el-table-column label="权重" width="72">
          <template #default="{ row }">{{ row.weight_pct }}%</template>
        </el-table-column>
        <el-table-column label="Δ USD" width="100">
          <template #default="{ row }">{{ usd(row.summary?.delta_usd) }}</template>
        </el-table-column>
        <el-table-column label="Θ" width="80">
          <template #default="{ row }">{{ greekVal(row.summary?.net?.theta, 2) }}</template>
        </el-table-column>
        <el-table-column label="V" width="80">
          <template #default="{ row }">{{ greekVal(row.summary?.net?.vega, 2) }}</template>
        </el-table-column>
        <el-table-column label="保证金" min-width="100">
          <template #default="{ row }">{{ usd(row.summary?.margin_used_usd) }}</template>
        </el-table-column>
      </el-table>

      <el-table
        v-if="legs.length && !compact && !isMulti"
        :data="legs"
        size="small"
        stripe
        class="legs-table"
        max-height="220"
      >
        <el-table-column prop="label" label="腿" min-width="140" />
        <el-table-column label="Δ" width="72">
          <template #default="{ row }">{{ greekVal(row.contribution?.delta) }}</template>
        </el-table-column>
        <el-table-column label="Γ" width="80">
          <template #default="{ row }">{{ greekVal(row.contribution?.gamma, 6) }}</template>
        </el-table-column>
        <el-table-column label="Θ" width="80">
          <template #default="{ row }">{{ greekVal(row.contribution?.theta, 2) }}</template>
        </el-table-column>
        <el-table-column label="V" width="80">
          <template #default="{ row }">{{ greekVal(row.contribution?.vega, 2) }}</template>
        </el-table-column>
        <el-table-column
          v-if="report.scale_mode === 'margin'"
          label="保证金"
          width="88"
        >
          <template #default="{ row }">{{ usd(row.margin_usd) }}</template>
        </el-table-column>
      </el-table>

      <p v-if="report.disclaimer" class="disclaimer muted small mt">
        {{ report.disclaimer }}
      </p>
    </template>
    <el-empty
      v-else
      :description="report?.reason || report?.error || '暂无组合 Greeks'"
    />
  </div>
</template>

<style scoped>
.head-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.metric-row {
  margin-bottom: 12px;
}
.metric-card {
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
}
.metric-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.metric-value {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.3;
}
.metric-sub {
  margin-top: 2px;
}
.scenario-row {
  margin-bottom: 10px;
}
.scenario-card {
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.hedge-hint {
  margin-bottom: 10px;
}
.alert-item {
  margin-bottom: 8px;
}
.legs-table {
  margin-top: 8px;
}
.mt {
  margin-top: 8px;
}
</style>
