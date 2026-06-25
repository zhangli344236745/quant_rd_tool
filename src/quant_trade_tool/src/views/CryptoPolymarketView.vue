<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  cryptoApi,
  type PolymarketAdvisorPick,
  type PolymarketAdvisorReport,
  type PolymarketArbConfig,
  type PolymarketClosePreview,
  type PolymarketEdgeHistoryPoint,
  type PolymarketEvent,
  type PolymarketLeaderboardItem,
  type PolymarketOpenPreview,
  type PolymarketOpportunity,
  type PolymarketPosition,
  type PolymarketScanHistoryItem,
  type PolymarketScanResult,
  type PolymarketStrategyType,
  type PolymarketSummary,
} from "@/api/crypto";
import { extractError } from "@/api/http";
import { formatBeijing } from "@/utils/datetime";

const loading = ref(false);
const saving = ref(false);
const previewLoading = ref(false);
const allMarkets = ref<PolymarketOpportunity[]>([]);
const openPositions = ref<PolymarketPosition[]>([]);
const closedPositions = ref<PolymarketPosition[]>([]);
const events = ref<PolymarketEvent[]>([]);
const scanHistory = ref<PolymarketScanHistoryItem[]>([]);
const summary = ref<PolymarketSummary | null>(null);
const builtinRunning = ref(false);
const watchlistInput = ref("");
const showAllMarkets = ref(false);
const positionTab = ref("open");
const strategyTab = ref<"all" | PolymarketStrategyType>("all");
const lastScanDuration = ref<number | null>(null);
const lastScanMeta = ref<Partial<PolymarketScanResult>>({});
const leaderboard = ref<PolymarketLeaderboardItem[]>([]);
const advisorReport = ref<PolymarketAdvisorReport | null>(null);
const minWinRate = ref(0.6);
const edgeTrendCache = ref<Record<string, PolymarketEdgeHistoryPoint[]>>({});

const previewVisible = ref(false);
const preview = ref<PolymarketOpenPreview | null>(null);
const pendingOpp = ref<PolymarketOpportunity | null>(null);

const closePreviewVisible = ref(false);
const closePreview = ref<PolymarketClosePreview | null>(null);
const pendingCloseId = ref("");

const config = reactive<PolymarketArbConfig>({
  top_n_volume: 50,
  watchlist_condition_ids: [],
  min_edge_bps: 30,
  taker_fee_bps: 200,
  min_size_shares: 10,
  min_liquidity_usd: 100,
  builtin_scan_enabled: false,
  builtin_interval_sec: 300,
  scan_dedupe_sec: 30,
  default_paper_size_shares: 100,
  alert_cooldown_sec: 900,
  min_volume24hr_usd: 5000,
  use_depth_for_opportunity: true,
  depth_target_shares: 100,
  enabled_strategies: ["binary_ask", "binary_bid", "multi_ask"],
});

const opportunities = computed(() => {
  let rows = showAllMarkets.value
    ? allMarkets.value
    : allMarkets.value.filter((r) => r.opportunity && !r.error && !r.skipped);
  if (strategyTab.value !== "all") {
    rows = rows.filter((r) => r.strategy_type === strategyTab.value);
  }
  return rows;
});

const strategyLabel: Record<string, string> = {
  binary_ask: "二元买入",
  binary_bid: "二元卖出",
  multi_ask: "多结果",
};

const recTagType: Record<string, "success" | "warning" | "info" | "danger"> = {
  strong_buy: "success",
  buy: "success",
  watch: "warning",
  pass: "info",
};

function rowKey(row: PolymarketOpportunity) {
  return `${row.condition_id}:${row.strategy_type || "binary_ask"}`;
}

async function onExpandChange(row: PolymarketOpportunity, expanded: PolymarketOpportunity[]) {
  const isOpen = expanded.some((r) => rowKey(r) === rowKey(row));
  if (!isOpen || !row.condition_id || edgeTrendCache.value[row.condition_id]) return;
  try {
    const { data } = await cryptoApi.polymarketEdgeTrend(row.condition_id, 24, row.strategy_type);
    edgeTrendCache.value[row.condition_id] = data.items ?? [];
  } catch {
    edgeTrendCache.value[row.condition_id] = [];
  }
}

function sparklinePoints(cid: string): string {
  const pts = edgeTrendCache.value[cid] || [];
  if (pts.length < 2) return "";
  const vals = pts.map((p) => Number(p.edge_at_size_bps ?? p.edge_bps ?? 0));
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  return vals
    .map((v, i) => {
      const x = (i / (vals.length - 1)) * 80;
      const y = 20 - ((v - min) / span) * 18;
      return `${x},${y}`;
    })
    .join(" ");
}

function num(v: number | undefined | null, d = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
}

function signedUsd(v: number | undefined | null, d = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  const prefix = v > 0 ? "+" : "";
  return prefix + num(v, d);
}

function profitClass(v: number | undefined | null) {
  if (v == null || Number.isNaN(v)) return "";
  if (v > 0) return "profit-pos";
  if (v < 0) return "profit-neg";
  return "";
}

async function loadConfig() {
  try {
    const { data } = await cryptoApi.polymarketGetConfig();
    Object.assign(config, data);
    watchlistInput.value = (data.watchlist_condition_ids || []).join(", ");
  } catch {
    /* defaults */
  }
}

async function refresh() {
  loading.value = true;
  try {
    const [scanRes, openRes, closedRes, sumRes, stRes, evRes, histRes, lbRes, advRes] = await Promise.all([
      cryptoApi.polymarketScanLatest(),
      cryptoApi.polymarketPositions({ status: "open" }),
      cryptoApi.polymarketPositions({ status: "closed", limit: 50 }),
      cryptoApi.polymarketStats(),
      cryptoApi.polymarketBuiltinStatus(),
      cryptoApi.polymarketEvents(50),
      cryptoApi.polymarketScanHistory(10),
      cryptoApi.polymarketLeaderboard(168, 10),
      cryptoApi.polymarketAdvisorRecommendations(minWinRate.value, 8),
    ]);
    allMarkets.value = scanRes.data?.items ?? [];
    openPositions.value = openRes.data?.items ?? [];
    closedPositions.value = closedRes.data?.items ?? [];
    summary.value = sumRes.data ?? null;
    builtinRunning.value = !!stRes.data?.running;
    events.value = (evRes.data?.items ?? []).reverse();
    scanHistory.value = histRes.data?.items ?? [];
    leaderboard.value = lbRes.data?.items ?? [];
    advisorReport.value = advRes.data ?? null;
    lastScanDuration.value = scanRes.data?.duration_sec ?? summary.value?.last_duration_sec ?? null;
    lastScanMeta.value = scanRes.data ?? {};
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

async function runScan() {
  loading.value = true;
  try {
    const { data } = await cryptoApi.polymarketScan(true);
    allMarkets.value = data.items ?? [];
    lastScanDuration.value = data.duration_sec ?? null;
    lastScanMeta.value = data;
    const dur = data.duration_sec != null ? ` · ${num(data.duration_sec, 1)}s` : "";
    ElMessage.success(`扫描完成：${data.opportunities_count} 个机会${dur}`);
    const sum = await cryptoApi.polymarketStats();
    summary.value = sum.data ?? null;
    const adv = await cryptoApi.polymarketAdvisorRecommendations(minWinRate.value, 8);
    advisorReport.value = adv.data ?? null;
    const [openRes, histRes] = await Promise.all([
      cryptoApi.polymarketPositions({ status: "open" }),
      cryptoApi.polymarketScanHistory(10),
    ]);
    openPositions.value = openRes.data?.items ?? [];
    scanHistory.value = histRes.data?.items ?? [];
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  saving.value = true;
  try {
    config.watchlist_condition_ids = watchlistInput.value
      .split(/[,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    await cryptoApi.polymarketPutConfig({ ...config });
    ElMessage.success("配置已保存");
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    saving.value = false;
  }
}

async function toggleBuiltin() {
  try {
    if (builtinRunning.value) {
      await cryptoApi.polymarketBuiltinStop();
      builtinRunning.value = false;
      config.builtin_scan_enabled = false;
    } else {
      await cryptoApi.polymarketBuiltinStart();
      builtinRunning.value = true;
      config.builtin_scan_enabled = true;
    }
    ElMessage.success(builtinRunning.value ? "内置扫描已启动" : "已停止");
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function openFromAdvisor(pick: PolymarketAdvisorPick) {
  const row = allMarkets.value.find(
    (r) => r.condition_id === pick.condition_id && r.strategy_type === pick.strategy_type,
  );
  if (row) await showOpenPreview(row);
  else ElMessage.warning("请刷新扫描后再试");
}

async function reloadAdvisor() {
  try {
    const { data } = await cryptoApi.polymarketAdvisorRecommendations(minWinRate.value, 8);
    advisorReport.value = data ?? null;
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function showOpenPreview(row: PolymarketOpportunity) {
  if (!row.condition_id) return;
  previewLoading.value = true;
  pendingOpp.value = row;
  try {
    const { data } = await cryptoApi.polymarketPreview(
      row.condition_id,
      config.default_paper_size_shares,
    );
    preview.value = data;
    previewVisible.value = true;
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    previewLoading.value = false;
  }
}

async function confirmOpen() {
  const row = pendingOpp.value;
  if (!row?.condition_id || row.ask_yes == null || row.ask_no == null) return;
  try {
    await cryptoApi.polymarketOpen({
      condition_id: row.condition_id,
      question: row.question,
      ask_yes: row.ask_yes,
      ask_no: row.ask_no,
      size_shares: config.default_paper_size_shares,
    });
    previewVisible.value = false;
    ElMessage.success("纸面仓位已开");
    await refresh();
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function showClosePreview(p: PolymarketPosition) {
  pendingCloseId.value = p.id;
  previewLoading.value = true;
  try {
    const { data } = await cryptoApi.polymarketClosePreview(p.id);
    closePreview.value = data;
    closePreviewVisible.value = true;
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    previewLoading.value = false;
  }
}

async function confirmClose() {
  if (!pendingCloseId.value) return;
  try {
    await cryptoApi.polymarketClose(pendingCloseId.value);
    closePreviewVisible.value = false;
    ElMessage.success("已平仓");
    await refresh();
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

onMounted(async () => {
  await loadConfig();
  await refresh();
});
</script>

<template>
  <div class="page">
    <header class="head">
      <div>
        <h1>Polymarket 套利</h1>
        <p class="sub">多策略套利扫描 · 深度吃单 · 纸面模拟（仅二元买入）</p>
      </div>
      <div class="actions">
        <el-button :loading="loading" @click="refresh">刷新</el-button>
        <el-button type="primary" :loading="loading" @click="runScan">立即扫描</el-button>
      </div>
    </header>

    <el-row :gutter="12" class="mb stats-row">
      <el-col :span="4">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">今日扫描</div>
          <div class="stat-value">{{ summary?.scans_today ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">今日机会</div>
          <div class="stat-value">{{ summary?.opportunities_today ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">最佳 edge</div>
          <div class="stat-value">{{ num(summary?.best_edge_bps_today ?? summary?.best_edge_bps, 1) }} bps</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">上次耗时</div>
          <div class="stat-value">{{ lastScanDuration != null ? `${num(lastScanDuration, 1)}s` : "—" }}</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">持仓 / 已平</div>
          <div class="stat-value">{{ summary?.open_positions ?? 0 }} / {{ summary?.closed_positions ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">累计盈亏</div>
          <div class="stat-value" :class="profitClass(summary?.total_realized_pnl_usd)">
            {{ signedUsd(summary?.total_realized_pnl_usd, 2) }}
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-alert
      v-if="lastScanMeta.markets_scanned_ok != null"
      class="mb scan-health"
      type="info"
      :closable="false"
      show-icon
      :title="`扫描健康：成功 ${lastScanMeta.markets_scanned_ok ?? 0} · 跳过 ${lastScanMeta.markets_skipped ?? 0} · 错误 ${lastScanMeta.markets_errors ?? 0}`"
    />

    <el-row :gutter="16" class="mb">
      <el-col :span="8">
        <el-card shadow="never">
          <template #header>调度</template>
          <p>最近扫描 {{ formatBeijing(summary?.last_scan_at, "datetime_min") }}</p>
          <p>市场 {{ summary?.markets_scanned ?? 0 }} · 机会 {{ summary?.opportunities_count ?? 0 }}</p>
          <el-button class="mt" @click="toggleBuiltin">
            {{ builtinRunning ? "停止内置扫描" : "启动内置扫描" }}
          </el-button>
          <router-link to="/schedules" class="link">定时任务</router-link>
        </el-card>
        <el-card shadow="never" class="mt">
          <template #header>机会排行榜 (7d)</template>
          <el-table :data="leaderboard" size="small" max-height="180">
            <el-table-column prop="question" label="市场" min-width="120" show-overflow-tooltip />
            <el-table-column prop="hit_count" label="命中" width="50" />
            <el-table-column label="最佳edge" width="80">
              <template #default="{ row }">{{ num(row.best_edge_at_size_bps ?? row.best_edge_bps, 0) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
        <el-card shadow="never" class="mt">
          <template #header>扫描历史</template>
          <el-table :data="scanHistory" size="small" max-height="200">
            <el-table-column label="时间" min-width="150">
              <template #default="{ row }">{{ formatBeijing(row.scanned_at, "datetime_min") }}</template>
            </el-table-column>
            <el-table-column prop="opportunities_count" label="机会" width="50" />
            <el-table-column label="edge" width="60">
              <template #default="{ row }">{{ num(row.best_edge_bps, 0) }}</template>
            </el-table-column>
            <el-table-column label="耗时" width="50">
              <template #default="{ row }">{{ row.duration_sec != null ? `${num(row.duration_sec, 1)}s` : "—" }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card shadow="never">
          <template #header>配置</template>
          <el-form label-width="140px" size="small">
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="Top N 成交量">
                  <el-input-number v-model="config.top_n_volume" :min="5" :max="200" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="最小 edge bps">
                  <el-input-number v-model="config.min_edge_bps" :min="0" :max="500" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Taker 费 bps/腿">
                  <el-input-number v-model="config.taker_fee_bps" :min="0" :max="500" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="最小流动性 USD">
                  <el-input-number v-model="config.min_liquidity_usd" :min="0" :step="10" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="最小份额">
                  <el-input-number v-model="config.min_size_shares" :min="0" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="内置间隔秒">
                  <el-input-number v-model="config.builtin_interval_sec" :min="30" :max="3600" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="扫描去重秒">
                  <el-input-number v-model="config.scan_dedupe_sec" :min="0" :max="600" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="告警冷却秒">
                  <el-input-number v-model="config.alert_cooldown_sec" :min="0" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="纸面份额">
                  <el-input-number v-model="config.default_paper_size_shares" :min="1" :max="10000" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="关注 condition_id">
                  <el-input v-model="watchlistInput" placeholder="逗号分隔" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="mb advisor-card" v-loading="loading">
      <template #header>
        <div class="card-head">
          <span>投资建议 · 高胜率优选</span>
          <div class="advisor-controls">
            <span class="ctrl-label">最低胜率</span>
            <el-slider v-model="minWinRate" :min="0.4" :max="0.9" :step="0.05" :format-tooltip="(v: number) => `${(v * 100).toFixed(0)}%`" style="width: 140px" @change="reloadAdvisor" />
            <el-button size="small" @click="reloadAdvisor">刷新</el-button>
          </div>
        </div>
      </template>
      <p v-if="advisorReport?.disclaimer" class="advisor-disclaimer">{{ advisorReport.disclaimer }}</p>
      <p v-if="advisorReport" class="advisor-meta">
        当前 {{ advisorReport.total_opportunities }} 个机会 · 胜率≥{{ (advisorReport.min_win_rate * 100).toFixed(0) }}% 共 {{ advisorReport.high_win_rate_count }} 个
      </p>
      <el-empty v-if="!advisorReport?.top_picks?.length" description="暂无高胜率推荐，请先扫描或降低胜率阈值" />
      <div v-else class="advisor-grid">
        <div v-for="pick in advisorReport.top_picks" :key="`${pick.condition_id}:${pick.strategy_type}`" class="advisor-item">
          <div class="advisor-item-head">
            <el-tag :type="recTagType[pick.recommendation] || 'info'" size="small">{{ pick.recommendation_label }}</el-tag>
            <span class="advisor-score">评分 {{ num(pick.score, 0) }}</span>
          </div>
          <div class="advisor-q">{{ pick.question }}</div>
          <div class="advisor-metrics">
            <span>胜率 <strong>{{ num(pick.win_rate_pct, 1) }}%</strong></span>
            <span>净利 <strong :class="profitClass(pick.profit_analysis?.net_profit_usd)">{{ signedUsd(pick.profit_analysis?.net_profit_usd, 2) }}</strong></span>
            <span>ROI <strong>{{ num(pick.profit_analysis?.roi_pct, 1) }}%</strong></span>
            <span>建议 {{ num(pick.profit_analysis?.recommended_size_shares, 0) }} 份</span>
          </div>
          <p class="advisor-text">{{ pick.advice }}</p>
          <el-button
            v-if="pick.paper_tradable && pick.recommendation !== 'pass' && pick.recommendation !== 'watch'"
            size="small"
            type="primary"
            link
            @click="openFromAdvisor(pick)"
          >
            纸面开仓
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="mb" v-loading="loading">
      <template #header>
        <div class="card-head">
          <div class="card-head-left">
            <span>套利机会</span>
            <el-radio-group v-model="strategyTab" size="small" class="strategy-tabs">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="binary_ask">二元买入</el-radio-button>
              <el-radio-button value="binary_bid">二元卖出</el-radio-button>
              <el-radio-button value="multi_ask">多结果</el-radio-button>
            </el-radio-group>
          </div>
          <el-switch
            v-model="showAllMarkets"
            active-text="全部市场"
            inactive-text="仅机会"
            inline-prompt
          />
        </div>
      </template>
      <el-table
        :data="opportunities"
        size="small"
        stripe
        max-height="420"
        :row-key="rowKey"
        @expand-change="onExpandChange"
      >
        <el-table-column type="expand" width="40">
          <template #default="{ row }">
            <div class="expand-panel">
              <div v-if="row.opportunity" class="profit-banner">
                深度 @{{ config.depth_target_shares }} 份预期收益
                <strong :class="profitClass(row.profit_at_size_usd ?? row.profit_at_100_usd)">
                  {{ signedUsd(row.profit_at_size_usd ?? row.profit_at_100_usd, 2) }}
                </strong>
                · edge@size {{ num(row.edge_at_size_bps ?? row.edge_bps, 1) }} bps
                <span v-if="row.slippage_bps != null"> · 滑点 {{ num(row.slippage_bps, 1) }} bps</span>
              </div>
              <el-row v-if="row.yes_ladder?.length || row.no_ladder?.length" :gutter="12">
                <el-col v-if="row.yes_ladder?.length" :span="12">
                  <div class="ladder-title">YES 深度</div>
                  <el-table :data="row.yes_ladder" size="small">
                    <el-table-column prop="price" label="价" width="70" />
                    <el-table-column prop="size" label="量" width="70" />
                    <el-table-column prop="take" label="吃单" width="70" />
                  </el-table>
                </el-col>
                <el-col v-if="row.no_ladder?.length" :span="12">
                  <div class="ladder-title">NO 深度</div>
                  <el-table :data="row.no_ladder" size="small">
                    <el-table-column prop="price" label="价" width="70" />
                    <el-table-column prop="size" label="量" width="70" />
                    <el-table-column prop="take" label="吃单" width="70" />
                  </el-table>
                </el-col>
              </el-row>
              <svg
                v-if="row.condition_id && sparklinePoints(row.condition_id)"
                class="sparkline"
                viewBox="0 0 80 22"
              >
                <polyline :points="sparklinePoints(row.condition_id)" fill="none" stroke="var(--el-color-primary)" stroke-width="1.5" />
              </svg>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="策略" width="88">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ strategyLabel[row.strategy_type || "binary_ask"] || row.strategy_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="市场" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <a
              v-if="row.market_url"
              :href="row.market_url"
              target="_blank"
              rel="noopener"
              class="market-link"
            >{{ row.question }}</a>
            <span v-else>{{ row.question }}</span>
          </template>
        </el-table-column>
        <el-table-column label="24h量" width="80">
          <template #default="{ row }">{{ num(row.volume24hr, 0) }}</template>
        </el-table-column>
        <el-table-column label="YES" width="70">
          <template #default="{ row }">{{ num(row.ask_yes, 3) }}</template>
        </el-table-column>
        <el-table-column label="NO" width="70">
          <template #default="{ row }">{{ num(row.ask_no, 3) }}</template>
        </el-table-column>
        <el-table-column label="edge@size" width="85">
          <template #default="{ row }">
            <el-tag v-if="row.opportunity" type="success">{{ num(row.edge_at_size_bps ?? row.edge_bps, 1) }}</el-tag>
            <span v-else>{{ num(row.edge_at_size_bps ?? row.edge_bps, 1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="收益@100份" width="110">
          <template #default="{ row }">
            <template v-if="row.opportunity">
              <span :class="profitClass(row.profit_at_100_usd)">
                {{ signedUsd(row.profit_at_100_usd, 2) }}
              </span>
              <span v-if="row.roi_at_100_pct != null" class="roi-hint">
                ({{ num(row.roi_at_100_pct, 1) }}%)
              </span>
            </template>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="可成交" width="75">
          <template #default="{ row }">{{ num(row.fillable_shares ?? row.size_cap, 0) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.opportunity && row.paper_tradable !== false && row.strategy_type !== 'binary_bid' && row.strategy_type !== 'multi_ask'"
              size="small"
              type="primary"
              link
              :loading="previewLoading"
              @click="showOpenPreview(row)"
            >
              纸面开仓
            </el-button>
            <el-tooltip v-else-if="row.opportunity" content="该策略仅支持扫描预览">
              <span class="preview-only">预览</span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <el-tabs v-model="positionTab" class="pos-tabs">
              <el-tab-pane label="持仓中" name="open" />
              <el-tab-pane label="已平仓" name="closed" />
            </el-tabs>
          </template>
          <el-table
            v-if="positionTab === 'open'"
            :data="openPositions"
            size="small"
            stripe
          >
            <el-table-column prop="question" label="市场" min-width="160" show-overflow-tooltip />
            <el-table-column prop="size_shares" label="份额" width="70" />
            <el-table-column label="成本" width="80">
              <template #default="{ row }">{{ num(row.cost_usd, 2) }}</template>
            </el-table-column>
            <el-table-column label="浮动盈亏" width="90">
              <template #default="{ row }">
                <span :class="profitClass(row.live_status?.unrealized_pnl_usd)">
                  {{ signedUsd(row.live_status?.unrealized_pnl_usd, 2) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="当前 edge" width="85">
              <template #default="{ row }">{{ num(row.live_status?.current_edge_bps, 1) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="70">
              <template #default="{ row }">
                <el-button size="small" type="warning" link @click="showClosePreview(row)">平仓</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-table
            v-else
            :data="closedPositions"
            size="small"
            stripe
          >
            <el-table-column prop="question" label="市场" min-width="180" show-overflow-tooltip />
            <el-table-column prop="size_shares" label="份额" width="70" />
            <el-table-column label="已实现盈亏" width="100">
              <template #default="{ row }">
                <span :class="profitClass(row.realized_pnl_usd)">{{ signedUsd(row.realized_pnl_usd, 2) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="平仓时间" min-width="120">
              <template #default="{ row }">{{ formatBeijing(row.closed_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>事件流</template>
          <div class="events-feed">
            <div v-for="(ev, i) in events" :key="i" class="event-row">
              <span class="event-ts">{{ formatBeijing(ev.ts, "time") }}</span>
              <el-tag size="small" type="info">{{ ev.type }}</el-tag>
              <span class="event-body">{{ ev.question || ev.condition_id || ev.position_id || "" }}</span>
            </div>
            <p v-if="!events.length" class="empty">暂无事件</p>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="previewVisible" title="开仓预览" width="480px">
      <template v-if="preview">
        <p class="preview-q">{{ preview.question }}</p>
        <el-descriptions :column="1" size="small" border>
          <el-descriptions-item label="份额">{{ preview.size_shares }}</el-descriptions-item>
          <el-descriptions-item label="YES 价">{{ num(preview.ask_yes, 4) }}</el-descriptions-item>
          <el-descriptions-item label="NO 价">{{ num(preview.ask_no, 4) }}</el-descriptions-item>
          <el-descriptions-item label="成本">{{ num(preview.cost_usd, 2) }} USDC</el-descriptions-item>
          <el-descriptions-item label="费用">{{ num(preview.fee_usd, 2) }} USDC</el-descriptions-item>
          <el-descriptions-item label="结算 payout">{{ num(preview.payout_usd, 2) }} USDC</el-descriptions-item>
          <el-descriptions-item label="预期净利">
            <span :class="profitClass(preview.net_pnl_usd)">{{ signedUsd(preview.net_pnl_usd, 2) }} USDC</span>
          </el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="previewVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmOpen">确认开仓</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="closePreviewVisible" title="平仓预览" width="480px">
      <template v-if="closePreview">
        <p class="preview-q">{{ closePreview.question }}</p>
        <el-descriptions :column="1" size="small" border>
          <el-descriptions-item label="份额">{{ closePreview.size_shares }}</el-descriptions-item>
          <el-descriptions-item label="成本">{{ num(closePreview.cost_usd, 2) }} USDC</el-descriptions-item>
          <el-descriptions-item label="费用">{{ num(closePreview.fee_usd, 2) }} USDC</el-descriptions-item>
          <el-descriptions-item label="结算 payout">{{ num(closePreview.payout_usd, 2) }} USDC</el-descriptions-item>
          <el-descriptions-item label="净盈亏">
            <span :class="profitClass(closePreview.net_pnl_usd)">{{ signedUsd(closePreview.net_pnl_usd, 2) }} USDC</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="closePreview.live_status" label="当前 edge">
            {{ num(closePreview.live_status.current_edge_bps, 1) }} bps
          </el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="closePreviewVisible = false">取消</el-button>
        <el-button type="warning" @click="confirmClose">确认平仓</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px 20px 32px; }
.head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.head h1 { margin: 0 0 6px; font-size: 22px; }
.sub { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
.actions { display: flex; gap: 8px; }
.mb { margin-bottom: 16px; }
.mt { margin-top: 12px; }
.link { margin-left: 12px; font-size: 13px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.card-head-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.strategy-tabs { margin-left: 8px; }
.scan-health { margin-bottom: 16px; }
.expand-panel { padding: 8px 12px 12px; }
.profit-banner { margin-bottom: 10px; font-size: 13px; padding: 8px 10px; background: var(--el-fill-color-light); border-radius: 6px; }
.ladder-title { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 6px; }
.sparkline { width: 80px; height: 22px; margin-top: 8px; }
.preview-only { font-size: 12px; color: var(--el-text-color-secondary); }
.advisor-card :deep(.el-card__header) { padding-bottom: 8px; }
.advisor-controls { display: flex; align-items: center; gap: 10px; }
.ctrl-label { font-size: 12px; color: var(--el-text-color-secondary); }
.advisor-disclaimer { font-size: 12px; color: var(--el-text-color-secondary); margin: 0 0 8px; }
.advisor-meta { font-size: 13px; margin: 0 0 12px; }
.advisor-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.advisor-item { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 12px; background: var(--el-fill-color-blank); }
.advisor-item-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.advisor-score { font-size: 12px; color: var(--el-text-color-secondary); }
.advisor-q { font-weight: 500; font-size: 14px; margin-bottom: 8px; line-height: 1.4; }
.advisor-metrics { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; margin-bottom: 8px; }
.advisor-text { font-size: 12px; color: var(--el-text-color-regular); line-height: 1.5; margin: 0 0 8px; }
.market-link { color: var(--el-color-primary); text-decoration: none; }
.market-link:hover { text-decoration: underline; }
.stats-row .stat-card { text-align: center; }
.stat-label { font-size: 12px; color: var(--el-text-color-secondary); }
.stat-value { font-size: 18px; font-weight: 600; margin-top: 4px; }
.profit-pos { color: var(--el-color-success); }
.profit-neg { color: var(--el-color-danger); }
.roi-hint { margin-left: 4px; font-size: 11px; color: var(--el-text-color-secondary); }
.pos-tabs :deep(.el-tabs__header) { margin: 0; }
.events-feed { max-height: 280px; overflow-y: auto; }
.event-row { display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--el-border-color-lighter); font-size: 12px; }
.event-ts { color: var(--el-text-color-secondary); min-width: 64px; }
.event-body { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty { color: var(--el-text-color-secondary); font-size: 13px; text-align: center; padding: 24px 0; }
.preview-q { font-weight: 500; margin: 0 0 12px; }
</style>
