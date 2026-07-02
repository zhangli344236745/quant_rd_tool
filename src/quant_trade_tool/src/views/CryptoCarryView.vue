<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  cryptoApi,
  type CarryClosePreview,
  type CarryConfig,
  type CarryExecutionPlan,
  type CarryOpportunity,
  type CarryPosition,
  type CarryPreview,
  type CarryPriceGuidance,
  type CarryProfitEstimate,
  type CarryRiskWarning,
  type CarrySummary,
} from "@/api/crypto";
import { extractError } from "@/api/http";
import TermLabel from "@/components/TermLabel.vue";
import { useNotify } from "@/composables/useNotify";
import { CARRY_GLOSSARY, CARRY_TERM_HINTS } from "./carryGlossary";

const notify = useNotify();

const loading = ref(false);
const saving = ref(false);
const previewLoading = ref(false);
const error = ref("");
const opportunities = ref<CarryOpportunity[]>([]);
const openPositions = ref<CarryPosition[]>([]);
const summary = ref<CarrySummary | null>(null);
const previewVisible = ref(false);
const preview = ref<CarryPreview | null>(null);
const closePreviewVisible = ref(false);
const closePreview = ref<CarryClosePreview | null>(null);
const pendingSymbol = ref("");
const pendingPositionId = ref("");
const glossaryOpen = ref<string[]>([]);

const H = CARRY_TERM_HINTS;

const config = reactive<CarryConfig>({
  watchlist: ["BTC", "ETH", "SOL", "BNB"],
  quote: "USDT",
  entry_threshold_apr: 0.15,
  exit_threshold_apr: 0.05,
  default_notional_usdt: 10_000,
  spot_fee_pct: 0.001,
  perp_fee_pct: 0.001,
  slippage_pct: 0.0005,
  testnet: false,
});

const watchlistInput = ref("BTC, ETH, SOL, BNB");

const entryPct = computed({
  get: () => config.entry_threshold_apr * 100,
  set: (v: number) => {
    config.entry_threshold_apr = v / 100;
  },
});

const exitPct = computed({
  get: () => config.exit_threshold_apr * 100,
  set: (v: number) => {
    config.exit_threshold_apr = v / 100;
  },
});

function pct(v: number | undefined | null, digits = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return (v * 100).toFixed(digits) + "%";
}

function num(v: number | undefined | null, digits = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function signedUsdt(v: number | undefined | null, digits = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  const prefix = v > 0 ? "+" : "";
  return prefix + num(v, digits);
}

function profitClass(v: number | undefined | null) {
  if (v == null || Number.isNaN(v)) return "";
  if (v > 0) return "profit-pos";
  if (v < 0) return "profit-neg";
  return "";
}

function rowProfit(row: CarryOpportunity): CarryProfitEstimate | null {
  if (row.profit_estimate) return row.profit_estimate;
  if (row.price_guidance?.profit_summary) return row.price_guidance.profit_summary;
  const ei = row.carry_plan?.expected_income;
  if (!ei) return null;
  const notional = row.notional_usdt ?? config.default_notional_usdt;
  const openFees = row.carry_plan?.open_fees_usdt ?? 0;
  return {
    notional_usdt: notional,
    funding_per_8h_usdt: ei.funding_per_8h_usdt,
    funding_daily_usdt: ei.funding_daily_usdt,
    funding_7d_usdt: ei.funding_7d_usdt ?? ei.funding_daily_usdt * 7,
    funding_30d_usdt: ei.funding_30d_usdt ?? ei.funding_daily_usdt * 30,
    funding_annual_usdt: ei.funding_annual_usdt,
    open_cost_usdt: openFees,
    round_trip_cost_usdt: openFees,
    net_daily_after_open_fee_usdt: ei.net_daily_after_open_fee_usdt,
    net_7d_after_open_cost_usdt: (ei.funding_7d_usdt ?? ei.funding_daily_usdt * 7) - openFees,
    net_30d_after_open_cost_usdt: (ei.funding_30d_usdt ?? ei.funding_daily_usdt * 30) - openFees,
    breakeven_days: null,
  };
}

function positionProfit(row: CarryPosition): CarryProfitEstimate | null {
  const hold = row.live_status?.expected_income_if_hold;
  if (hold?.funding_daily_usdt != null) return hold;
  const ei = row.execution_plan?.expected_income;
  if (!ei) return null;
  const openFees = row.execution_plan?.open_fees_usdt ?? row.total_fees ?? 0;
  return {
    notional_usdt: row.notional_usdt,
    funding_per_8h_usdt: ei.funding_per_8h_usdt,
    funding_daily_usdt: ei.funding_daily_usdt,
    funding_7d_usdt: ei.funding_7d_usdt ?? ei.funding_daily_usdt * 7,
    funding_30d_usdt: ei.funding_30d_usdt ?? ei.funding_daily_usdt * 30,
    funding_annual_usdt: ei.funding_annual_usdt,
    open_cost_usdt: openFees,
    round_trip_cost_usdt: openFees,
    net_daily_after_open_fee_usdt: ei.net_daily_after_open_fee_usdt,
    net_7d_after_open_cost_usdt: (ei.funding_7d_usdt ?? ei.funding_daily_usdt * 7) - openFees,
    net_30d_after_open_cost_usdt: (ei.funding_30d_usdt ?? ei.funding_daily_usdt * 30) - openFees,
    breakeven_days: null,
  };
}

function positionPriceGuidance(row: CarryPosition): CarryPriceGuidance | null {
  return row.live_status?.price_guidance ?? null;
}

function incomeBrief(p: CarryProfitEstimate | null) {
  if (!p) return "";
  return `日 ${signedUsdt(p.funding_daily_usdt)} · 7日净 ${signedUsdt(p.net_7d_after_open_cost_usdt)} · 30日净 ${signedUsdt(p.net_30d_after_open_cost_usdt)}`;
}

const bestEntryOpportunity = computed(() => {
  const candidates = opportunities.value.filter((r) => r.entry_alert && !r.error && !r.has_open_position);
  if (!candidates.length) return null;
  return candidates.reduce((best, row) => {
    const p = rowProfit(row);
    const bestP = rowProfit(best);
    const daily = p?.funding_daily_usdt ?? 0;
    const bestDaily = bestP?.funding_daily_usdt ?? 0;
    return daily > bestDaily ? row : best;
  });
});

const previewProfitHero = computed(() => {
  const p = preview.value?.profit_estimate;
  if (!p) return null;
  return [
    { label: "预估日收益", value: p.funding_daily_usdt, sub: "funding 毛收益" },
    { label: "7 日净收益", value: p.net_7d_after_open_cost_usdt, sub: "扣开仓成本" },
    { label: "30 日净收益", value: p.net_30d_after_open_cost_usdt, sub: "扣开仓成本" },
    { label: "年化收益", value: p.funding_annual_usdt, sub: "按当前费率" },
  ];
});

function estDailyFunding(row: CarryOpportunity) {
  const p = rowProfit(row);
  if (p) return p.funding_daily_usdt;
  if (row.funding_rate == null) return null;
  return row.funding_rate * config.default_notional_usdt * 3;
}

function parseWatchlist(raw: string): string[] {
  return raw
    .split(/[,，\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
}

function riskTagType(level: CarryRiskWarning["level"]) {
  if (level === "high") return "danger";
  if (level === "medium") return "warning";
  return "info";
}

async function loadScan() {
  loading.value = true;
  error.value = "";
  try {
    const { data: scan } = await cryptoApi.carryScan();
    opportunities.value = scan.items ?? [];
    openPositions.value = scan.positions ?? [];
    summary.value = scan.summary ?? null;
    if (scan.config) Object.assign(config, scan.config);
    watchlistInput.value = (scan.config?.watchlist ?? config.watchlist).join(", ");
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  saving.value = true;
  try {
    config.watchlist = parseWatchlist(watchlistInput.value);
    const { data } = await cryptoApi.carryPutConfig({ ...config });
    Object.assign(config, data);
    watchlistInput.value = data.watchlist.join(", ");
    notify.success("配置已保存");
    await loadScan();
  } catch (e) {
    notify.error("保存失败", extractError(e));
  } finally {
    saving.value = false;
  }
}

async function openCarry(row: CarryOpportunity) {
  if (!row.entry_alert || row.has_open_position) return;
  previewLoading.value = true;
  pendingSymbol.value = row.symbol;
  try {
    const { data } = await cryptoApi.carryPreview({
      symbol: row.symbol,
      notional_usdt: config.default_notional_usdt,
    });
    preview.value = data;
    previewVisible.value = true;
  } catch (e) {
    notify.error("加载预览失败", extractError(e));
  } finally {
    previewLoading.value = false;
  }
}

async function confirmOpenCarry() {
  if (!preview.value?.can_open) return;
  previewLoading.value = true;
  try {
    await cryptoApi.carryOpen({
      symbol: preview.value.symbol,
      notional_usdt: preview.value.notional_usdt,
      spot_mark: preview.value.market.spot_mark,
      perp_mark: preview.value.market.perp_mark,
      funding_rate: preview.value.market.funding_rate,
    });
    previewVisible.value = false;
    notify.success(`${preview.value.symbol} 纸面 Carry 已开仓`);
    await loadScan();
  } catch (e) {
    notify.error("开仓失败", extractError(e));
  } finally {
    previewLoading.value = false;
  }
}

async function closeCarry(pos: CarryPosition) {
  previewLoading.value = true;
  pendingPositionId.value = pos.id;
  pendingSymbol.value = pos.symbol;
  try {
    const { data } = await cryptoApi.carryClosePreview(pos.id);
    closePreview.value = data;
    closePreviewVisible.value = true;
  } catch (e) {
    notify.error("加载平仓预览失败", extractError(e));
  } finally {
    previewLoading.value = false;
  }
}

async function confirmCloseCarry() {
  if (!closePreview.value?.can_close) return;
  previewLoading.value = true;
  try {
    await cryptoApi.carryClose(closePreview.value.position_id, {
      spot_mark: closePreview.value.market.spot_mark,
      perp_mark: closePreview.value.market.perp_mark,
      funding_rate: closePreview.value.market.funding_rate,
    });
    closePreviewVisible.value = false;
    notify.success(`${closePreview.value.symbol} 已平仓`);
    await loadScan();
  } catch (e) {
    notify.error("平仓失败", extractError(e));
  } finally {
    previewLoading.value = false;
  }
}

function opportunityExitAlert(symbol: string) {
  const row = opportunities.value.find((x) => x.symbol === symbol);
  return Boolean(row?.exit_alert);
}

function legTagType(market: string) {
  return market === "spot" ? "success" : "warning";
}

function formatLegSteps(plan: CarryExecutionPlan | undefined) {
  if (!plan?.steps?.length) return [];
  return plan.steps;
}

const openIncomeRows = computed(() => {
  const plan = preview.value?.execution_plan;
  if (!plan?.expected_income) return [];
  const inc = plan.expected_income;
  return [
    { label: "每 8h funding", value: signedUsdt(inc.funding_per_8h_usdt) + " USDT" },
    { label: "预估日 funding", value: signedUsdt(inc.funding_daily_usdt) + " USDT" },
    { label: "7 日 funding", value: signedUsdt(inc.funding_7d_usdt) + " USDT" },
    { label: "30 日 funding", value: signedUsdt(inc.funding_30d_usdt) + " USDT" },
    { label: "年化 funding", value: signedUsdt(inc.funding_annual_usdt) + " USDT" },
    {
      label: "日净额（扣开仓费）",
      value: signedUsdt(inc.net_daily_after_open_fee_usdt) + " USDT",
    },
  ];
});

const openProfitRows = computed(() => {
  const p = preview.value;
  if (!p) return [];
  const e = p.profit_estimate;
  return [
    { label: "每 8h funding", value: signedUsdt(e.funding_per_8h_usdt) + " USDT", hint: H.funding8h },
    { label: "预估日 funding", value: signedUsdt(e.funding_daily_usdt) + " USDT", hint: H.estDailyFunding },
    { label: "7 日 funding（毛）", value: signedUsdt(e.funding_7d_usdt) + " USDT", hint: "按当前费率连续 7 天估算，未扣成本。" },
    { label: "7 日净额（扣开仓成本）", value: signedUsdt(e.net_7d_after_open_cost_usdt) + " USDT", hint: H.net7d },
    { label: "30 日 funding（毛）", value: signedUsdt(e.funding_30d_usdt) + " USDT", hint: "按当前费率连续 30 天估算。" },
    { label: "30 日净额（扣开仓成本）", value: signedUsdt(e.net_30d_after_open_cost_usdt) + " USDT", hint: H.net7d },
    { label: "年化 funding（毛）", value: signedUsdt(e.funding_annual_usdt) + " USDT", hint: H.funding8h },
    { label: "基差年化参考", value: signedUsdt(e.basis_annual_hint_usdt) + " USDT", hint: H.basisAnnualHint },
    { label: "开仓成本（费+滑点）", value: num(e.open_cost_usdt) + " USDT", hint: H.openCost },
    { label: "开平仓总成本", value: num(e.round_trip_cost_usdt) + " USDT", hint: H.roundTripCost },
    {
      label: "收回总成本约",
      value: e.breakeven_days != null ? e.breakeven_days + " 天" : "—",
      hint: H.breakevenDays,
    },
  ];
});

const closeLegRows = computed(() => {
  const plan = closePreview.value?.execution_plan;
  return formatLegSteps(plan);
});

const closePnlBreakdownRows = computed(() => {
  const b = closePreview.value?.pnl_breakdown;
  if (!b) return [];
  return [
    { label: "已入账 funding", value: signedUsdt(b.accrued_funding_usdt) + " USDT" },
    { label: "现货腿浮盈", value: signedUsdt(b.spot_leg_mtm_usdt) + " USDT" },
    { label: "永续腿浮盈", value: signedUsdt(b.perp_leg_mtm_usdt) + " USDT" },
    { label: "基差盈亏（若平仓）", value: signedUsdt(b.basis_pnl_if_close_usdt) + " USDT" },
    { label: "开仓已付手续费", value: "-" + num(b.open_fees_paid_usdt) + " USDT" },
    { label: "预估平仓手续费", value: "-" + num(b.close_fees_est_usdt) + " USDT" },
    {
      label: "若此刻平仓总盈亏",
      value: signedUsdt(b.unrealized_pnl_if_close_now_usdt) + " USDT",
      highlight: true,
    },
  ];
});

const closeProfitRows = computed(() => {
  const p = closePreview.value;
  if (!p) return [];
  const e = p.pnl_estimate;
  return [
    { label: "Funding 合计", value: signedUsdt(e.funding_component_usdt) + " USDT", hint: H.accruedFundingCol },
    { label: "基差盈亏", value: signedUsdt(e.basis_pnl) + " USDT", hint: H.basisPnl },
    {
      label: "基差变化",
      value: (e.basis_change_bps > 0 ? "+" : "") + num(e.basis_change_bps, 2) + " bps",
      hint: H.basisBps,
    },
    { label: "总手续费", value: signedUsdt(e.fee_component_usdt) + " USDT", hint: H.roundTripCost },
    { label: "预估已实现盈亏", value: signedUsdt(e.realized_pnl) + " USDT", hint: H.realizedPnlEst },
  ];
});

onMounted(loadScan);
</script>

<template>
  <div class="page">
    <header class="head">
      <div>
        <h1>Carry 套息套利（纸面）</h1>
        <p class="sub">
          做多现货 + 做空永续，赚资金费率；本页仅纸面记账，不下真实单。不确定的参数可点
          <el-icon class="inline-icon"><QuestionFilled /></el-icon>
          查看说明。
        </p>
      </div>
      <div class="head-actions">
        <el-button :loading="loading" type="primary" @click="loadScan">刷新扫描</el-button>
      </div>
    </header>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-collapse v-model="glossaryOpen" class="mb glossary">
      <el-collapse-item title="术语说明（看不懂的参数点这里）" name="glossary">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item v-for="item in CARRY_GLOSSARY" :key="item.term" :label="item.term">
            {{ item.desc }}
          </el-descriptions-item>
        </el-descriptions>
      </el-collapse-item>
    </el-collapse>

    <el-row :gutter="16" class="mb">
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">
            <TermLabel label="开放仓" :hint="H.openCount" />
          </div>
          <div class="stat-value">{{ summary?.open_count ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">
            <TermLabel label="可入场信号" :hint="H.entryAlert" />
          </div>
          <div class="stat-value warn">{{ summary?.entry_alert_count ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">
            <TermLabel label="累计已实现盈亏" :hint="H.realizedPnl" />
          </div>
          <div class="stat-value">{{ num(summary?.total_realized_pnl) }} USDT</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">
            <TermLabel label="开放仓累计 funding" :hint="H.accruedFunding" />
          </div>
          <div class="stat-value">{{ num(summary?.total_accrued_funding) }} USDT</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mb">
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">
            <TermLabel label="开放仓名义" :hint="H.openNotional" />
          </div>
          <div class="stat-value">{{ num(summary?.total_open_notional_usdt, 0) }} USDT</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">
            <TermLabel label="开放仓浮动盈亏" :hint="H.unrealizedPnl" />
          </div>
          <div class="stat-value" :class="profitClass(summary?.total_unrealized_pnl_usdt)">
            {{ signedUsdt(summary?.total_unrealized_pnl_usdt) }} USDT
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">
            <TermLabel label="开放仓预估日收入" :hint="H.openDailyIncome" />
          </div>
          <div class="stat-value" :class="profitClass(summary?.total_open_daily_income_usdt)">
            {{ signedUsdt(summary?.total_open_daily_income_usdt) }} USDT
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">
            <TermLabel label="可入场日收入合计" :hint="H.scanEntryDaily" />
          </div>
          <div class="stat-value" :class="profitClass(summary?.scan_entry_daily_income_usdt)">
            {{ signedUsdt(summary?.scan_entry_daily_income_usdt) }} USDT
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="mb">
      <template #header>策略配置</template>
      <el-form label-width="140px" class="config-form">
        <el-form-item>
          <template #label>
            <TermLabel label="监控列表" :hint="H.watchlist" />
          </template>
          <el-input v-model="watchlistInput" style="width: 360px" placeholder="BTC, ETH, SOL, BNB" />
        </el-form-item>
        <el-form-item>
          <template #label>
            <TermLabel label="入场综合年化 ≥" :hint="H.entryApr" />
          </template>
          <el-input-number v-model="entryPct" :min="0" :max="200" :step="1" /> %
          <span class="field-hint">默认 15%，即 Composite APR 达到 15% 才提示可入场</span>
        </el-form-item>
        <el-form-item>
          <template #label>
            <TermLabel label="退出综合年化 ≤" :hint="H.exitApr" />
          </template>
          <el-input-number v-model="exitPct" :min="-50" :max="100" :step="1" /> %
          <span class="field-hint">默认 5%，低于此值或 funding 转负时提示关注退出</span>
        </el-form-item>
        <el-form-item>
          <template #label>
            <TermLabel label="默认名义金额" :hint="H.notional" />
          </template>
          <el-input-number v-model="config.default_notional_usdt" :min="100" :step="1000" /> USDT
          <span class="field-hint">开纸面仓时模拟的仓位规模（USDT）</span>
        </el-form-item>
        <el-form-item>
          <el-button :loading="saving" type="primary" @click="saveConfig">保存配置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="mb">
      <template #header>
        <span>扫描机会</span>
        <span class="header-hint">（名义 {{ num(config.default_notional_usdt, 0) }} USDT 下的预估套利收益）</span>
      </template>

      <el-alert
        v-if="bestEntryOpportunity && rowProfit(bestEntryOpportunity)"
        type="success"
        :closable="false"
        show-icon
        class="mb profit-banner"
      >
        <template #title>
          最佳入场：{{ bestEntryOpportunity.symbol }} · 名义 {{ num(config.default_notional_usdt, 0) }} USDT
        </template>
        <template #default>
          <div class="profit-banner-grid">
            <span>
              日收益 <strong :class="profitClass(rowProfit(bestEntryOpportunity)!.funding_daily_usdt)">
                {{ signedUsdt(rowProfit(bestEntryOpportunity)!.funding_daily_usdt) }} USDT
              </strong>
            </span>
            <span>
              7 日净收益 <strong :class="profitClass(rowProfit(bestEntryOpportunity)!.net_7d_after_open_cost_usdt)">
                {{ signedUsdt(rowProfit(bestEntryOpportunity)!.net_7d_after_open_cost_usdt) }} USDT
              </strong>
            </span>
            <span>
              30 日净收益 <strong :class="profitClass(rowProfit(bestEntryOpportunity)!.net_30d_after_open_cost_usdt)">
                {{ signedUsdt(rowProfit(bestEntryOpportunity)!.net_30d_after_open_cost_usdt) }} USDT
              </strong>
            </span>
            <span>
              年化 <strong :class="profitClass(rowProfit(bestEntryOpportunity)!.funding_annual_usdt)">
                {{ signedUsdt(rowProfit(bestEntryOpportunity)!.funding_annual_usdt) }} USDT
              </strong>
              （{{ pct(bestEntryOpportunity.composite_apr) }}）
            </span>
          </div>
        </template>
      </el-alert>

      <el-table v-loading="loading" :data="opportunities" stripe>
        <el-table-column type="expand" width="40">
          <template #default="{ row }">
            <div v-if="row.carry_plan" class="expand-plan">
              <div v-if="rowProfit(row)" class="income-banner mb">
                <div class="income-banner-title">预期收益（按当前 funding，静态估算）</div>
                <div class="income-banner-grid">
                  <div>
                    <span class="income-k">日收益</span>
                    <strong :class="profitClass(rowProfit(row)!.funding_daily_usdt)">
                      {{ signedUsdt(rowProfit(row)!.funding_daily_usdt) }} USDT
                    </strong>
                  </div>
                  <div>
                    <span class="income-k">7 日净收益</span>
                    <strong :class="profitClass(rowProfit(row)!.net_7d_after_open_cost_usdt)">
                      {{ signedUsdt(rowProfit(row)!.net_7d_after_open_cost_usdt) }} USDT
                    </strong>
                  </div>
                  <div>
                    <span class="income-k">30 日净收益</span>
                    <strong :class="profitClass(rowProfit(row)!.net_30d_after_open_cost_usdt)">
                      {{ signedUsdt(rowProfit(row)!.net_30d_after_open_cost_usdt) }} USDT
                    </strong>
                  </div>
                  <div>
                    <span class="income-k">年化</span>
                    <strong :class="profitClass(rowProfit(row)!.funding_annual_usdt)">
                      {{ signedUsdt(rowProfit(row)!.funding_annual_usdt) }} USDT
                    </strong>
                  </div>
                </div>
              </div>
              <h4 class="mini-title">套利执行步骤</h4>
              <p class="plan-summary">{{ row.carry_plan.summary }}</p>
              <el-timeline>
                <el-timeline-item
                  v-for="step in row.carry_plan.steps"
                  :key="step.order"
                  :type="legTagType(step.market)"
                  :timestamp="`步骤 ${step.order}`"
                >
                  <div class="leg-title">
                    <el-tag size="small" :type="legTagType(step.market)">{{ step.side_label }}</el-tag>
                    <span>{{ step.description }}</span>
                  </div>
                  <div v-if="step.fee_usdt != null" class="hint">
                    手续费约 {{ num(step.fee_usdt) }} USDT
                  </div>
                </el-timeline-item>
              </el-timeline>
              <div v-if="row.carry_plan.expected_income" class="plan-income">
                <span>每 8h：{{ signedUsdt(row.carry_plan.expected_income.funding_per_8h_usdt) }} USDT</span>
                <span>扣费后日净：{{ signedUsdt(row.carry_plan.expected_income.net_daily_after_open_fee_usdt) }} USDT</span>
                <span>开仓手续费：{{ num(row.carry_plan.open_fees_usdt) }} USDT</span>
              </div>
              <div v-if="row.price_guidance?.available" class="price-guidance mt">
                <h4 class="mini-title">价格与风控参考</h4>
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item>
                    <template #label><TermLabel label="现货买入" :hint="H.spotBuyPrice" /></template>
                    {{ num(row.price_guidance.spot_buy_price) }}
                  </el-descriptions-item>
                  <el-descriptions-item>
                    <template #label><TermLabel label="永续开空" :hint="H.perpShortPrice" /></template>
                    {{ num(row.price_guidance.perp_short_price) }}
                  </el-descriptions-item>
                  <el-descriptions-item>
                    <template #label><TermLabel label="止损参考" :hint="H.stopLoss" /></template>
                    {{ num(row.price_guidance.stop_loss_perp_mark) }}
                    <span v-if="row.price_guidance.stop_loss_pnl_usdt != null" class="hint">
                      （约 {{ signedUsdt(row.price_guidance.stop_loss_pnl_usdt) }} USDT）
                    </span>
                  </el-descriptions-item>
                  <el-descriptions-item>
                    <template #label><TermLabel label="止盈参考" :hint="H.takeProfit" /></template>
                    {{ num(row.price_guidance.take_profit_perp_mark) }}
                    <span v-if="row.price_guidance.take_profit_pnl_usdt != null" class="hint">
                      （目标 {{ signedUsdt(row.price_guidance.take_profit_pnl_usdt) }} USDT）
                    </span>
                  </el-descriptions-item>
                </el-descriptions>
                <p v-if="row.price_guidance.stop_loss_hint" class="hint mt-sm">{{ row.price_guidance.stop_loss_hint }}</p>
                <p v-if="row.price_guidance.take_profit_hint" class="hint">{{ row.price_guidance.take_profit_hint }}</p>
              </div>
            </div>
            <span v-else class="hint">暂无套利方案</span>
          </template>
        </el-table-column>
        <el-table-column prop="symbol" width="90">
          <template #header>
            <TermLabel label="币种" :hint="H.symbol" />
          </template>
        </el-table-column>
        <el-table-column width="120">
          <template #header>
            <TermLabel label="基差 (bps)" :hint="H.basisBps" />
          </template>
          <template #default="{ row }">{{ num(row.basis_bps, 2) }}</template>
        </el-table-column>
        <el-table-column width="120">
          <template #header>
            <TermLabel label="资金费率" :hint="H.fundingRate" />
          </template>
          <template #default="{ row }">{{ pct(row.funding_rate, 4) }}</template>
        </el-table-column>
        <el-table-column width="130">
          <template #header>
            <TermLabel label="套利日收益" :hint="H.estDailyFunding" />
          </template>
          <template #default="{ row }">
            <strong :class="profitClass(rowProfit(row)?.funding_daily_usdt)">
              {{ signedUsdt(rowProfit(row)?.funding_daily_usdt) }}
            </strong>
            <span class="unit"> USDT</span>
          </template>
        </el-table-column>
        <el-table-column width="130">
          <template #header>
            <TermLabel label="7日净收益" :hint="H.net7d" />
          </template>
          <template #default="{ row }">
            <strong :class="profitClass(rowProfit(row)?.net_7d_after_open_cost_usdt)">
              {{ signedUsdt(rowProfit(row)?.net_7d_after_open_cost_usdt) }}
            </strong>
            <span class="unit"> USDT</span>
          </template>
        </el-table-column>
        <el-table-column width="130">
          <template #header>
            <TermLabel label="30日净收益" :hint="H.net7d" />
          </template>
          <template #default="{ row }">
            <strong :class="profitClass(rowProfit(row)?.net_30d_after_open_cost_usdt)">
              {{ signedUsdt(rowProfit(row)?.net_30d_after_open_cost_usdt) }}
            </strong>
            <span class="unit"> USDT</span>
          </template>
        </el-table-column>
        <el-table-column width="130">
          <template #header>
            <TermLabel label="年化收益" :hint="H.funding8h" />
          </template>
          <template #default="{ row }">
            <strong :class="profitClass(rowProfit(row)?.funding_annual_usdt)">
              {{ signedUsdt(rowProfit(row)?.funding_annual_usdt) }}
            </strong>
            <span class="unit"> USDT</span>
          </template>
        </el-table-column>
        <el-table-column width="100">
          <template #header>
            <TermLabel label="综合年化" :hint="H.compositeApr" />
          </template>
          <template #default="{ row }">{{ pct(row.composite_apr) }}</template>
        </el-table-column>
        <el-table-column width="110">
          <template #header>
            <TermLabel label="现货买入" :hint="H.spotBuyPrice" />
          </template>
          <template #default="{ row }">
            {{ num(row.price_guidance?.spot_buy_price ?? row.spot_mark) }}
          </template>
        </el-table-column>
        <el-table-column width="110">
          <template #header>
            <TermLabel label="永续开空" :hint="H.perpShortPrice" />
          </template>
          <template #default="{ row }">
            {{ num(row.price_guidance?.perp_short_price ?? row.perp_mark) }}
          </template>
        </el-table-column>
        <el-table-column width="110">
          <template #header>
            <TermLabel label="止损参考" :hint="H.stopLoss" />
          </template>
          <template #default="{ row }">
            <span v-if="row.price_guidance?.stop_loss_perp_mark != null">
              {{ num(row.price_guidance.stop_loss_perp_mark) }}
            </span>
            <span v-else class="hint">—</span>
          </template>
        </el-table-column>
        <el-table-column width="110">
          <template #header>
            <TermLabel label="止盈参考" :hint="H.takeProfit" />
          </template>
          <template #default="{ row }">
            <span v-if="row.price_guidance?.take_profit_perp_mark != null">
              {{ num(row.price_guidance.take_profit_perp_mark) }}
            </span>
            <span v-else class="hint">—</span>
          </template>
        </el-table-column>
        <el-table-column label="套利操作（默认名义）" min-width="200">
          <template #default="{ row }">
            <template v-if="row.carry_plan">
              <div class="leg-brief">
                <el-tag size="small" type="success">买现货</el-tag>
                {{ num(row.carry_plan.base_amount, 4) }} {{ row.symbol }}
              </div>
              <div class="leg-brief">
                <el-tag size="small" type="warning">空永续</el-tag>
                {{ num(row.carry_plan.base_amount, 4) }} {{ row.symbol }}
              </div>
              <div v-if="rowProfit(row)" class="leg-income hint">
                {{ incomeBrief(rowProfit(row)) }}
              </div>
            </template>
            <span v-else-if="row.error" class="err">{{ row.error }}</span>
            <span v-else class="hint">—</span>
          </template>
        </el-table-column>
        <el-table-column label="告警" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.error" type="danger">错误</el-tag>
            <el-tag v-else-if="row.entry_alert" type="success">可入场</el-tag>
            <el-tag v-else type="info">—</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              :loading="previewLoading && pendingSymbol === row.symbol"
              :disabled="!row.entry_alert || row.has_open_position || !!row.error"
              @click="openCarry(row)"
            >
              开纸面 Carry
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="160">
          <template #default="{ row }">
            <span v-if="row.error" class="err">{{ row.error }}</span>
            <span v-else-if="row.has_open_position">已有开放仓</span>
            <span v-else class="hint">名义 {{ num(config.default_notional_usdt, 0) }} USDT</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>开放纸面 Carry</template>
      <el-table v-loading="loading" :data="openPositions" stripe>
        <el-table-column type="expand" width="40">
          <template #default="{ row }">
            <div v-if="row.live_status" class="expand-plan">
              <div v-if="positionProfit(row)" class="income-banner mb">
                <div class="income-banner-title">继续持有预期收入（按当前 funding）</div>
                <div class="income-banner-grid">
                  <div>
                    <span class="income-k">日收益</span>
                    <strong :class="profitClass(positionProfit(row)!.funding_daily_usdt)">
                      {{ signedUsdt(positionProfit(row)!.funding_daily_usdt) }} USDT
                    </strong>
                  </div>
                  <div>
                    <span class="income-k">7 日净</span>
                    <strong :class="profitClass(positionProfit(row)!.net_7d_after_open_cost_usdt)">
                      {{ signedUsdt(positionProfit(row)!.net_7d_after_open_cost_usdt) }} USDT
                    </strong>
                  </div>
                  <div>
                    <span class="income-k">30 日净</span>
                    <strong :class="profitClass(positionProfit(row)!.net_30d_after_open_cost_usdt)">
                      {{ signedUsdt(positionProfit(row)!.net_30d_after_open_cost_usdt) }} USDT
                    </strong>
                  </div>
                  <div>
                    <span class="income-k">年化</span>
                    <strong :class="profitClass(positionProfit(row)!.funding_annual_usdt)">
                      {{ signedUsdt(positionProfit(row)!.funding_annual_usdt) }} USDT
                    </strong>
                  </div>
                </div>
              </div>
              <p class="plan-summary">{{ row.live_status.open_plan.summary || "当前持仓双腿" }}</p>
              <el-timeline>
                <el-timeline-item
                  v-for="step in row.live_status.open_plan.steps"
                  :key="step.order"
                  :type="legTagType(step.market)"
                  :timestamp="`腿 ${step.order}`"
                >
                  <div class="leg-title">
                    <el-tag size="small" :type="legTagType(step.market)">{{ step.side_label }}</el-tag>
                    <span>{{ step.description }}</span>
                  </div>
                </el-timeline-item>
              </el-timeline>
              <h4 class="mini-title">若此刻平仓盈亏拆分</h4>
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="Funding 合计">
                  {{ signedUsdt(row.live_status.pnl_breakdown.accrued_funding_usdt) }} USDT
                </el-descriptions-item>
                <el-descriptions-item label="现货腿浮盈">
                  {{ signedUsdt(row.live_status.pnl_breakdown.spot_leg_mtm_usdt) }} USDT
                </el-descriptions-item>
                <el-descriptions-item label="永续腿浮盈">
                  {{ signedUsdt(row.live_status.pnl_breakdown.perp_leg_mtm_usdt) }} USDT
                </el-descriptions-item>
                <el-descriptions-item label="若此刻平仓总盈亏">
                  <strong>{{ signedUsdt(row.live_status.pnl_breakdown.unrealized_pnl_if_close_now_usdt) }} USDT</strong>
                </el-descriptions-item>
              </el-descriptions>
              <div v-if="positionPriceGuidance(row)?.available" class="price-guidance mt">
                <h4 class="mini-title">入场价与风控参考</h4>
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="入场现货">
                    {{ num(positionPriceGuidance(row)!.entry_spot_price) }}
                  </el-descriptions-item>
                  <el-descriptions-item label="入场永续">
                    {{ num(positionPriceGuidance(row)!.entry_perp_price) }}
                  </el-descriptions-item>
                  <el-descriptions-item>
                    <template #label><TermLabel label="平仓卖现货" :hint="H.spotSellPrice" /></template>
                    {{ num(positionPriceGuidance(row)!.spot_sell_price) }}
                  </el-descriptions-item>
                  <el-descriptions-item>
                    <template #label><TermLabel label="平仓回补永续" :hint="H.perpCoverPrice" /></template>
                    {{ num(positionPriceGuidance(row)!.perp_cover_price) }}
                  </el-descriptions-item>
                  <el-descriptions-item>
                    <template #label><TermLabel label="止损参考" :hint="H.stopLoss" /></template>
                    {{ num(positionPriceGuidance(row)!.stop_loss_perp_mark) }}
                  </el-descriptions-item>
                  <el-descriptions-item>
                    <template #label><TermLabel label="止盈参考" :hint="H.takeProfit" /></template>
                    {{ num(positionPriceGuidance(row)!.take_profit_perp_mark) }}
                  </el-descriptions-item>
                </el-descriptions>
              </div>
            </div>
            <div v-else-if="row.execution_plan" class="expand-plan">
              <div v-if="positionProfit(row)" class="income-banner mb">
                <div class="income-banner-title">开仓时预期收入（快照）</div>
                <div class="income-banner-grid">
                  <div>
                    <span class="income-k">日收益</span>
                    <strong>{{ signedUsdt(positionProfit(row)!.funding_daily_usdt) }} USDT</strong>
                  </div>
                  <div>
                    <span class="income-k">7 日净</span>
                    <strong>{{ signedUsdt(positionProfit(row)!.net_7d_after_open_cost_usdt) }} USDT</strong>
                  </div>
                </div>
              </div>
              <el-timeline>
                <el-timeline-item
                  v-for="step in row.execution_plan.steps"
                  :key="step.order"
                  :type="legTagType(step.market)"
                >
                  {{ step.description }}
                </el-timeline-item>
              </el-timeline>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="symbol" width="90">
          <template #header>
            <TermLabel label="币种" :hint="H.symbol" />
          </template>
        </el-table-column>
        <el-table-column width="140">
          <template #header>
            <TermLabel label="持仓数量" :hint="H.notionalItem" />
          </template>
          <template #default="{ row }">{{ num(row.base_amount, 4) }} {{ row.symbol }}</template>
        </el-table-column>
        <el-table-column width="120">
          <template #header>
            <TermLabel label="名义金额" :hint="H.notionalItem" />
          </template>
          <template #default="{ row }">{{ num(row.notional_usdt, 0) }} USDT</template>
        </el-table-column>
        <el-table-column width="100">
          <template #header>
            <TermLabel label="入场现货" :hint="H.spotBuyPrice" />
          </template>
          <template #default="{ row }">
            {{ num(positionPriceGuidance(row)?.entry_spot_price ?? row.spot_entry) }}
          </template>
        </el-table-column>
        <el-table-column width="100">
          <template #header>
            <TermLabel label="入场永续" :hint="H.perpShortPrice" />
          </template>
          <template #default="{ row }">
            {{ num(positionPriceGuidance(row)?.entry_perp_price ?? row.perp_entry) }}
          </template>
        </el-table-column>
        <el-table-column width="100">
          <template #header>
            <TermLabel label="止损参考" :hint="H.stopLoss" />
          </template>
          <template #default="{ row }">
            {{ num(positionPriceGuidance(row)?.stop_loss_perp_mark) }}
          </template>
        </el-table-column>
        <el-table-column width="100">
          <template #header>
            <TermLabel label="止盈参考" :hint="H.takeProfit" />
          </template>
          <template #default="{ row }">
            {{ num(positionPriceGuidance(row)?.take_profit_perp_mark) }}
          </template>
        </el-table-column>
        <el-table-column width="120">
          <template #header>
            <TermLabel label="累计 funding" :hint="H.accruedFundingCol" />
          </template>
          <template #default="{ row }">
            <strong :class="profitClass(row.accrued_funding)">{{ signedUsdt(row.accrued_funding) }}</strong>
            <span class="unit"> USDT</span>
          </template>
        </el-table-column>
        <el-table-column width="120">
          <template #header>
            <TermLabel label="预估日收益" :hint="H.estDailyFunding" />
          </template>
          <template #default="{ row }">
            <strong :class="profitClass(positionProfit(row)?.funding_daily_usdt)">
              {{ signedUsdt(positionProfit(row)?.funding_daily_usdt) }}
            </strong>
            <span class="unit"> USDT</span>
          </template>
        </el-table-column>
        <el-table-column width="120">
          <template #header>
            <TermLabel label="7日净收益" :hint="H.net7d" />
          </template>
          <template #default="{ row }">
            <strong :class="profitClass(positionProfit(row)?.net_7d_after_open_cost_usdt)">
              {{ signedUsdt(positionProfit(row)?.net_7d_after_open_cost_usdt) }}
            </strong>
            <span class="unit"> USDT</span>
          </template>
        </el-table-column>
        <el-table-column width="120">
          <template #header>
            <TermLabel label="30日净收益" :hint="H.net7d" />
          </template>
          <template #default="{ row }">
            <strong :class="profitClass(positionProfit(row)?.net_30d_after_open_cost_usdt)">
              {{ signedUsdt(positionProfit(row)?.net_30d_after_open_cost_usdt) }}
            </strong>
            <span class="unit"> USDT</span>
          </template>
        </el-table-column>
        <el-table-column width="140">
          <template #header>
            <TermLabel label="若此刻平仓盈亏" :hint="H.realizedPnlEst" />
          </template>
          <template #default="{ row }">
            <strong :class="profitClass(row.live_status?.pnl_breakdown?.unrealized_pnl_if_close_now_usdt)">
              {{ signedUsdt(row.live_status?.pnl_breakdown?.unrealized_pnl_if_close_now_usdt) }}
            </strong>
            <span class="unit"> USDT</span>
          </template>
        </el-table-column>
        <el-table-column width="100">
          <template #header>
            <TermLabel label="退出提示" :hint="H.exitAlert" />
          </template>
          <template #default="{ row }">
            <el-tag v-if="opportunityExitAlert(row.symbol)" type="warning">建议关注</el-tag>
            <el-tag v-else type="info">—</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="entry_ts" min-width="150" label="开仓时间" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button
              size="small"
              type="danger"
              :loading="previewLoading && pendingPositionId === row.id"
              @click="closeCarry(row)"
            >
              平仓
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && openPositions.length === 0" description="暂无开放纸面 Carry" />
    </el-card>

    <el-dialog
      v-model="previewVisible"
      :title="`开仓预览 · ${preview?.symbol ?? ''}`"
      width="720px"
      destroy-on-close
    >
      <template v-if="preview">
        <div v-if="previewProfitHero" class="profit-hero mb">
          <div v-for="item in previewProfitHero" :key="item.label" class="profit-hero-card">
            <div class="profit-hero-label">{{ item.label }}</div>
            <div class="profit-hero-value" :class="profitClass(item.value)">
              {{ signedUsdt(item.value) }} <span class="unit">USDT</span>
            </div>
            <div class="profit-hero-sub">{{ item.sub }}</div>
          </div>
        </div>
        <p class="profit-hero-note">
          名义 {{ num(preview.notional_usdt, 0) }} USDT · 开仓成本约
          {{ num(preview.profit_estimate.open_cost_usdt) }} USDT ·
          收回成本约 {{ preview.profit_estimate.breakeven_days ?? "—" }} 天
        </p>

        <div v-if="preview.price_guidance?.available" class="price-guidance mb">
          <h3 class="section-title">价格与风控参考</h3>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item>
              <template #label><TermLabel label="现货买入" :hint="H.spotBuyPrice" /></template>
              {{ num(preview.price_guidance.spot_buy_price) }}
            </el-descriptions-item>
            <el-descriptions-item>
              <template #label><TermLabel label="永续开空" :hint="H.perpShortPrice" /></template>
              {{ num(preview.price_guidance.perp_short_price) }}
            </el-descriptions-item>
            <el-descriptions-item>
              <template #label><TermLabel label="止损参考" :hint="H.stopLoss" /></template>
              {{ num(preview.price_guidance.stop_loss_perp_mark) }}
              <span v-if="preview.price_guidance.stop_loss_pnl_usdt != null" class="hint">
                （约 {{ signedUsdt(preview.price_guidance.stop_loss_pnl_usdt) }} USDT）
              </span>
            </el-descriptions-item>
            <el-descriptions-item>
              <template #label><TermLabel label="止盈参考" :hint="H.takeProfit" /></template>
              {{ num(preview.price_guidance.take_profit_perp_mark) }}
              <span v-if="preview.price_guidance.take_profit_pnl_usdt != null" class="hint">
                （目标 {{ signedUsdt(preview.price_guidance.take_profit_pnl_usdt) }} USDT）
              </span>
            </el-descriptions-item>
          </el-descriptions>
          <p v-if="preview.price_guidance.stop_loss_hint" class="hint mt-sm">{{ preview.price_guidance.stop_loss_hint }}</p>
          <p v-if="preview.price_guidance.take_profit_hint" class="hint">{{ preview.price_guidance.take_profit_hint }}</p>
        </div>

        <h3 v-if="openIncomeRows.length" class="section-title">预期收益（按当前 funding）</h3>
        <el-table v-if="openIncomeRows.length" :data="openIncomeRows" size="small" stripe class="mb">
          <el-table-column prop="label" label="项目" min-width="160" />
          <el-table-column prop="value" label="估算" min-width="140" />
        </el-table>

        <h3 class="section-title">利润估算明细</h3>
        <el-table :data="openProfitRows" size="small" stripe class="mb">
          <el-table-column prop="label" label="项目" min-width="160" />
          <el-table-column prop="value" label="估算" min-width="120" />
          <el-table-column prop="hint" label="说明" min-width="200">
            <template #default="{ row }">
              <span class="hint">{{ row.hint }}</span>
            </template>
          </el-table-column>
        </el-table>

        <h3 class="section-title">套利执行方案（纸面模拟）</h3>
        <p v-if="preview.execution_plan" class="plan-summary mb">{{ preview.execution_plan.summary }}</p>
        <el-timeline v-if="preview.execution_plan" class="mb">
          <el-timeline-item
            v-for="step in preview.execution_plan.steps"
            :key="step.order"
            :type="legTagType(step.market)"
            :timestamp="`步骤 ${step.order}`"
          >
            <div class="leg-title">
              <el-tag :type="legTagType(step.market)">{{ step.side_label }}</el-tag>
              <strong v-if="step.base_amount">{{ num(step.base_amount, 6) }} {{ preview.symbol }}</strong>
              @ {{ num(step.price) }}
            </div>
            <p class="hint">{{ step.description }}</p>
            <p v-if="step.quote_amount_usdt != null" class="hint">
              名义约 {{ num(step.quote_amount_usdt) }} USDT，手续费 {{ num(step.fee_usdt) }} USDT
            </p>
          </el-timeline-item>
        </el-timeline>

        <el-descriptions :column="2" border size="small" class="mb">
          <el-descriptions-item>
            <template #label><TermLabel label="名义金额" :hint="H.notionalItem" /></template>
            {{ num(preview.notional_usdt, 0) }} USDT
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="综合年化" :hint="H.compositeApr" /></template>
            {{ pct(preview.market.composite_apr) }}
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="现货价" :hint="H.spotMark" /></template>
            {{ num(preview.market.spot_mark) }}
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="永续价" :hint="H.perpMark" /></template>
            {{ num(preview.market.perp_mark) }}
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="基差" :hint="H.basisBps" /></template>
            {{ num(preview.market.basis_bps, 2) }} bps
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="资金费率" :hint="H.fundingRate" /></template>
            {{ pct(preview.market.funding_rate, 4) }}
          </el-descriptions-item>
        </el-descriptions>

        <h3 class="section-title">风险提示</h3>
        <div class="risk-list">
          <el-alert
            v-for="(w, idx) in preview.risk_warnings"
            :key="idx"
            :type="riskTagType(w.level) as any"
            :title="w.title"
            :description="w.detail"
            show-icon
            :closable="false"
            class="risk-item"
          />
        </div>

        <p class="disclaimer">{{ preview.disclaimer }}</p>
      </template>

      <template #footer>
        <el-button @click="previewVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="previewLoading"
          :disabled="!preview?.can_open"
          @click="confirmOpenCarry"
        >
          确认开纸面 Carry
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="closePreviewVisible"
      :title="`平仓预览 · ${closePreview?.symbol ?? ''}`"
      width="720px"
      destroy-on-close
    >
      <template v-if="closePreview">
        <el-alert
          v-if="closePreview.exit_alert"
          type="warning"
          title="已触发退出告警"
          description="当前综合收益或 funding 状态建议关注退出时机。"
          show-icon
          :closable="false"
          class="mb"
        />

        <div v-if="closePreview.price_guidance?.available" class="price-guidance mb">
          <h3 class="section-title">平仓价格与风控参考</h3>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="入场现货">
              {{ num(closePreview.price_guidance.entry_spot_price) }}
            </el-descriptions-item>
            <el-descriptions-item label="入场永续">
              {{ num(closePreview.price_guidance.entry_perp_price) }}
            </el-descriptions-item>
            <el-descriptions-item>
              <template #label><TermLabel label="卖出现货" :hint="H.spotSellPrice" /></template>
              {{ num(closePreview.price_guidance.spot_sell_price) }}
            </el-descriptions-item>
            <el-descriptions-item>
              <template #label><TermLabel label="回补永续" :hint="H.perpCoverPrice" /></template>
              {{ num(closePreview.price_guidance.perp_cover_price) }}
            </el-descriptions-item>
            <el-descriptions-item>
              <template #label><TermLabel label="当前现货" :hint="H.spotMark" /></template>
              {{ num(closePreview.price_guidance.spot_mark) }}
            </el-descriptions-item>
            <el-descriptions-item>
              <template #label><TermLabel label="当前永续" :hint="H.perpMark" /></template>
              {{ num(closePreview.price_guidance.perp_mark) }}
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <h3 class="section-title">当前持仓（开仓时）</h3>
        <el-timeline v-if="closePreview.open_legs" class="mb">
          <el-timeline-item
            v-for="step in closePreview.open_legs.steps"
            :key="'open-' + step.order"
            :type="legTagType(step.market)"
          >
            <el-tag size="small" :type="legTagType(step.market)">{{ step.side_label }}</el-tag>
            {{ step.description }}
          </el-timeline-item>
        </el-timeline>

        <h3 class="section-title">平仓执行方案</h3>
        <p v-if="closePreview.execution_plan" class="plan-summary mb">{{ closePreview.execution_plan.summary }}</p>
        <el-timeline v-if="closePreview.execution_plan" class="mb">
          <el-timeline-item
            v-for="step in closeLegRows"
            :key="'close-' + step.order"
            :type="legTagType(step.market)"
            :timestamp="`步骤 ${step.order}`"
          >
            <div class="leg-title">
              <el-tag :type="legTagType(step.market)">{{ step.side_label }}</el-tag>
              <strong>{{ num(step.base_amount, 6) }} {{ closePreview.symbol }}</strong>
              @ {{ num(step.price) }}
            </div>
            <p class="hint">{{ step.description }}</p>
          </el-timeline-item>
        </el-timeline>

        <h3 v-if="closePnlBreakdownRows.length" class="section-title">盈亏拆分（若此刻平仓）</h3>
        <el-table v-if="closePnlBreakdownRows.length" :data="closePnlBreakdownRows" size="small" stripe class="mb">
          <el-table-column prop="label" label="项目" min-width="160" />
          <el-table-column prop="value" label="金额" min-width="140">
            <template #default="{ row }">
              <strong v-if="row.highlight">{{ row.value }}</strong>
              <span v-else>{{ row.value }}</span>
            </template>
          </el-table-column>
        </el-table>

        <el-descriptions :column="2" border size="small" class="mb">
          <el-descriptions-item>
            <template #label><TermLabel label="名义金额" :hint="H.notionalItem" /></template>
            {{ num(closePreview.notional_usdt, 0) }} USDT
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="持仓天数" :hint="H.holdDays" /></template>
            {{ closePreview.hold_days }} 天
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="已入账 funding" :hint="H.accruedFundingCol" /></template>
            {{ signedUsdt(closePreview.position_snapshot.accrued_funding_booked) }} USDT
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="待入账 funding" :hint="H.pendingFunding" /></template>
            {{ signedUsdt(closePreview.position_snapshot.pending_funding_usdt) }} USDT
            ({{ closePreview.position_snapshot.pending_periods }} 期)
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="入场基差" :hint="H.entryBasis" /></template>
            {{ num(closePreview.position_snapshot.entry_basis_bps, 2) }} bps
          </el-descriptions-item>
          <el-descriptions-item>
            <template #label><TermLabel label="当前基差" :hint="H.basisBps" /></template>
            {{ num(closePreview.market.basis_bps, 2) }} bps
          </el-descriptions-item>
        </el-descriptions>

        <h3 class="section-title">预估已实现盈亏（含待入账 funding）</h3>
        <el-table :data="closeProfitRows" size="small" stripe>
          <el-table-column prop="label" label="项目" min-width="160" />
          <el-table-column prop="value" label="估算" min-width="120" />
          <el-table-column prop="hint" label="说明" min-width="200">
            <template #default="{ row }">
              <span class="hint">{{ row.hint }}</span>
            </template>
          </el-table-column>
        </el-table>

        <h3 class="section-title">退出风险提示</h3>
        <div class="risk-list">
          <el-alert
            v-for="(w, idx) in closePreview.risk_warnings"
            :key="idx"
            :type="riskTagType(w.level) as any"
            :title="w.title"
            :description="w.detail"
            show-icon
            :closable="false"
            class="risk-item"
          />
        </div>

        <p class="disclaimer">{{ closePreview.disclaimer }}</p>
      </template>

      <template #footer>
        <el-button @click="closePreviewVisible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="previewLoading"
          :disabled="!closePreview?.can_close"
          @click="confirmCloseCarry"
        >
          确认平仓
        </el-button>
      </template>
    </el-dialog>
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
  gap: 16px;
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
.mt-sm {
  margin-top: 6px;
}
.price-guidance {
  padding: 8px 0;
}
.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.stat-value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 600;
}
.stat-value.warn {
  color: var(--el-color-warning);
}
.err {
  color: var(--el-color-danger);
  font-size: 12px;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.section-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
}
.risk-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.risk-item {
  margin: 0;
}
.disclaimer {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.glossary :deep(.el-collapse-item__header) {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.config-form .field-hint {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.inline-icon {
  vertical-align: -2px;
  color: var(--el-text-color-secondary);
}
.expand-plan {
  padding: 8px 16px 12px 8px;
}
.plan-summary {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.plan-income {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 8px;
}
.income-banner {
  padding: 12px 14px;
  border-radius: 8px;
  background: rgba(61, 214, 195, 0.08);
  border: 1px solid rgba(61, 214, 195, 0.25);
}
.income-banner-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}
.income-banner-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.income-k {
  display: block;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-bottom: 2px;
}
.leg-income {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.leg-brief {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  margin-bottom: 4px;
}
.leg-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}
.mini-title {
  margin: 12px 0 8px;
  font-size: 13px;
  font-weight: 600;
}
.header-hint {
  margin-left: 8px;
  font-size: 12px;
  font-weight: normal;
  color: var(--el-text-color-secondary);
}
.profit-banner-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16px 24px;
  margin-top: 4px;
  font-size: 13px;
}
.profit-pos {
  color: var(--el-color-success);
}
.profit-neg {
  color: var(--el-color-danger);
}
.unit {
  font-size: 11px;
  font-weight: normal;
  color: var(--el-text-color-secondary);
}
.profit-hero {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.profit-hero-card {
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
}
.profit-hero-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.profit-hero-value {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 700;
}
.profit-hero-sub {
  margin-top: 4px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.profit-hero-note {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
@media (max-width: 900px) {
  .profit-hero {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
