<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  cryptoApi,
  type PolymarketArbConfig,
  type PolymarketClosePreview,
  type PolymarketEvent,
  type PolymarketOpenPreview,
  type PolymarketOpportunity,
  type PolymarketPosition,
  type PolymarketScanHistoryItem,
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
const lastScanDuration = ref<number | null>(null);

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
});

const opportunities = computed(() =>
  showAllMarkets.value
    ? allMarkets.value
    : allMarkets.value.filter((r) => r.opportunity && !r.error),
);

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
    const [scanRes, openRes, closedRes, sumRes, stRes, evRes, histRes] = await Promise.all([
      cryptoApi.polymarketScanLatest(),
      cryptoApi.polymarketPositions({ status: "open" }),
      cryptoApi.polymarketPositions({ status: "closed", limit: 50 }),
      cryptoApi.polymarketStats(),
      cryptoApi.polymarketBuiltinStatus(),
      cryptoApi.polymarketEvents(50),
      cryptoApi.polymarketScanHistory(10),
    ]);
    allMarkets.value = scanRes.data?.items ?? [];
    openPositions.value = openRes.data?.items ?? [];
    closedPositions.value = closedRes.data?.items ?? [];
    summary.value = sumRes.data ?? null;
    builtinRunning.value = !!stRes.data?.running;
    events.value = (evRes.data?.items ?? []).reverse();
    scanHistory.value = histRes.data?.items ?? [];
    lastScanDuration.value = scanRes.data?.duration_sec ?? summary.value?.last_duration_sec ?? null;
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
    const dur = data.duration_sec != null ? ` · ${num(data.duration_sec, 1)}s` : "";
    ElMessage.success(`扫描完成：${data.opportunities_count} 个机会${dur}`);
    const sum = await cryptoApi.polymarketStats();
    summary.value = sum.data ?? null;
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
        <p class="sub">二元 YES+NO 卖一之和套利扫描 · 纸面模拟 · 研究用途</p>
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

    <el-card shadow="never" class="mb" v-loading="loading">
      <template #header>
        <div class="card-head">
          <span>套利机会</span>
          <el-switch
            v-model="showAllMarkets"
            active-text="全部市场"
            inactive-text="仅机会"
            inline-prompt
          />
        </div>
      </template>
      <el-table :data="opportunities" size="small" stripe max-height="420">
        <el-table-column prop="question" label="市场" min-width="200" show-overflow-tooltip>
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
        <el-table-column label="edge bps" width="85">
          <template #default="{ row }">
            <el-tag v-if="row.opportunity" type="success">{{ num(row.edge_bps, 1) }}</el-tag>
            <span v-else>{{ num(row.edge_bps, 1) }}</span>
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
        <el-table-column label="可成交量" width="80">
          <template #default="{ row }">{{ num(row.size_cap, 0) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.opportunity"
              size="small"
              type="primary"
              link
              :loading="previewLoading"
              @click="showOpenPreview(row)"
            >
              纸面开仓
            </el-button>
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
