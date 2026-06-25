<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  cryptoApi,
  type BinanceNewListing,
  type CoingeckoNewCoin,
  type HighVolatilityRow,
  type MarketRadarConfig,
  type MarketRadarEvent,
  type MarketRadarSummary,
} from "@/api/crypto";
import { extractError } from "@/api/http";
import { formatBeijing } from "@/utils/datetime";

const loading = ref(false);
const saving = ref(false);
const activeTab = ref("binance");
const volSort = ref<"change" | "vol">("change");
const binanceNew = ref<BinanceNewListing[]>([]);
const coingeckoNew = ref<CoingeckoNewCoin[]>([]);
const highVol = ref<HighVolatilityRow[]>([]);
const events = ref<MarketRadarEvent[]>([]);
const summary = ref<MarketRadarSummary | null>(null);
const builtinRunning = ref(false);
const lastScanAt = ref<string | null>(null);
const durationSec = ref<number | null>(null);

const config = reactive<MarketRadarConfig>({
  top_n_liquidity: 200,
  vol_lookback_hours: 24,
  vol_top_n_compute: 50,
  min_24h_change_pct: 8,
  min_realized_vol_pct: 5,
  builtin_scan_enabled: false,
  builtin_interval_sec: 600,
  scan_dedupe_sec: 60,
  alert_cooldown_sec: 1800,
  coingecko_per_page: 250,
});

const sortedHighVol = computed(() => {
  const rows = [...highVol.value];
  if (volSort.value === "vol") {
    rows.sort((a, b) => (b.realized_vol_pct ?? 0) - (a.realized_vol_pct ?? 0));
  } else {
    rows.sort((a, b) => b.abs_change_pct_24h - a.abs_change_pct_24h);
  }
  return rows;
});

const flaggedHighVol = computed(() => sortedHighVol.value.filter((r) => r.high_vol));

function num(v: number | undefined | null, d = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
}

function pctClass(v: number | undefined | null) {
  if (v == null || Number.isNaN(v)) return "";
  if (v > 0) return "profit-pos";
  if (v < 0) return "profit-neg";
  return "";
}

async function loadConfig() {
  try {
    const { data } = await cryptoApi.marketRadarGetConfig();
    Object.assign(config, data);
  } catch {
    /* defaults */
  }
}

async function saveConfig() {
  saving.value = true;
  try {
    const { data } = await cryptoApi.marketRadarPutConfig({ ...config });
    Object.assign(config, data);
    ElMessage.success("配置已保存");
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    saving.value = false;
  }
}

async function refresh(latestOnly = true) {
  loading.value = true;
  try {
    const [scanRes, sumRes, evRes, stRes] = await Promise.all([
      latestOnly ? cryptoApi.marketRadarScanLatest() : cryptoApi.marketRadarScan(true),
      cryptoApi.marketRadarSummary(),
      cryptoApi.marketRadarEvents(30),
      cryptoApi.marketRadarBuiltinStatus(),
    ]);
    binanceNew.value = scanRes.data.binance_new || [];
    coingeckoNew.value = scanRes.data.coingecko_new || [];
    highVol.value = scanRes.data.high_volatility || [];
    lastScanAt.value = scanRes.data.scanned_at || null;
    durationSec.value = scanRes.data.duration_sec ?? null;
    summary.value = sumRes.data;
    events.value = evRes.data.items || [];
    builtinRunning.value = stRes.data.running;
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

async function runScan() {
  loading.value = true;
  try {
    const { data } = await cryptoApi.marketRadarScan(true);
    binanceNew.value = data.binance_new || [];
    coingeckoNew.value = data.coingecko_new || [];
    highVol.value = data.high_volatility || [];
    lastScanAt.value = data.scanned_at || null;
    durationSec.value = data.duration_sec ?? null;
    ElMessage.success("扫描完成");
    await refresh(true);
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

async function toggleBuiltin() {
  try {
    if (builtinRunning.value) {
      await cryptoApi.marketRadarBuiltinStop();
      ElMessage.info("已停止内置扫描");
    } else {
      await cryptoApi.marketRadarBuiltinStart();
      ElMessage.success("已启动内置扫描");
    }
    const { data } = await cryptoApi.marketRadarBuiltinStatus();
    builtinRunning.value = data.running;
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

function openUrl(url?: string) {
  if (url) window.open(url, "_blank");
}

onMounted(async () => {
  await loadConfig();
  await refresh(true);
});
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="toolbar">
      <div>
        <h2>市场雷达</h2>
        <p class="sub">
          最近扫描：
          <span class="mono">{{ lastScanAt ? formatBeijing(lastScanAt, "datetime_min") : "—" }}</span>
          <span v-if="durationSec != null"> · {{ num(durationSec, 1) }}s</span>
        </p>
      </div>
      <div class="actions">
        <el-button @click="refresh(true)">刷新</el-button>
        <el-button type="primary" @click="runScan">立即扫描</el-button>
        <el-button :type="builtinRunning ? 'warning' : 'default'" @click="toggleBuiltin">
          {{ builtinRunning ? "停止定时" : "启动定时" }}
        </el-button>
      </div>
    </div>

    <el-row :gutter="12" class="stats">
      <el-col :span="6">
        <el-card shadow="never"><div class="stat-label">Binance 新上币</div><div class="stat-val">{{ summary?.binance_new_count ?? 0 }}</div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><div class="stat-label">CoinGecko 新币</div><div class="stat-val">{{ summary?.coingecko_new_count ?? 0 }}</div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><div class="stat-label">高波动标的</div><div class="stat-val">{{ summary?.high_volatility_flagged_count ?? flaggedHighVol.length }}</div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><div class="stat-label">定时扫描</div><div class="stat-val">{{ builtinRunning ? "运行中" : "已停止" }}</div></el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="config-card">
      <template #header>扫描配置</template>
      <el-form :inline="true" label-width="120px">
        <el-form-item label="流动性 Top N"><el-input-number v-model="config.top_n_liquidity" :min="50" :max="500" /></el-form-item>
        <el-form-item label="24h 涨跌阈值 %"><el-input-number v-model="config.min_24h_change_pct" :min="1" :max="50" :step="0.5" /></el-form-item>
        <el-form-item label="波动率阈值 %"><el-input-number v-model="config.min_realized_vol_pct" :min="1" :max="50" :step="0.5" /></el-form-item>
        <el-form-item label="波动率回看 h"><el-input-number v-model="config.vol_lookback_hours" :min="6" :max="72" /></el-form-item>
        <el-form-item label="定时间隔 s"><el-input-number v-model="config.builtin_interval_sec" :min="60" :max="3600" :step="60" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button></el-form-item>
      </el-form>
    </el-card>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="Binance 新上币" name="binance">
        <el-table :data="binanceNew" stripe empty-text="暂无新上币（首次扫描仅建立快照）">
          <el-table-column prop="symbol" label="交易对" width="140" />
          <el-table-column prop="market_type" label="市场" width="100" />
          <el-table-column prop="base" label="Base" width="100" />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="openUrl(row.trade_url)">交易页</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="全市场新币" name="coingecko">
        <el-table :data="coingeckoNew" stripe empty-text="暂无新收录币种">
          <el-table-column prop="symbol" label="Symbol" width="100" />
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column label="24h %" width="100">
            <template #default="{ row }"><span :class="pctClass(row.price_change_pct_24h)">{{ num(row.price_change_pct_24h) }}%</span></template>
          </el-table-column>
          <el-table-column label="市值" width="120">
            <template #default="{ row }">{{ num(row.market_cap_usd, 0) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="openUrl(row.detail_url)">CoinGecko</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="高波动榜" name="volatility">
        <div class="vol-toolbar">
          <span>排序：</span>
          <el-radio-group v-model="volSort" size="small">
            <el-radio-button value="change">24h 涨跌幅</el-radio-button>
            <el-radio-button value="vol">已实现波动率</el-radio-button>
          </el-radio-group>
          <span class="hint">高亮行 = 超过阈值</span>
        </div>
        <el-table :data="sortedHighVol" stripe empty-text="请先扫描" :row-class-name="({ row }) => (row.high_vol ? 'row-flag' : '')">
          <el-table-column prop="symbol" label="交易对" width="130" />
          <el-table-column label="价格" width="120"><template #default="{ row }">{{ num(row.price) }}</template></el-table-column>
          <el-table-column label="24h %" width="100">
            <template #default="{ row }"><span :class="pctClass(row.change_pct_24h)">{{ num(row.change_pct_24h) }}%</span></template>
          </el-table-column>
          <el-table-column label="波动率 %" width="110">
            <template #default="{ row }">{{ num(row.realized_vol_pct) }}%</template>
          </el-table-column>
          <el-table-column label="成交额 USDT" min-width="140">
            <template #default="{ row }">{{ num(row.quote_volume_usdt, 0) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }"><el-button link type="primary" @click="openUrl(row.trade_url)">交易</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="事件" name="events">
        <el-table :data="events" stripe empty-text="暂无事件">
          <el-table-column label="时间" width="160">
            <template #default="{ row }">{{ row.at ? formatBeijing(row.at, "datetime_min") : "—" }}</template>
          </el-table-column>
          <el-table-column prop="type" label="类型" width="160" />
          <el-table-column prop="title" label="标题" min-width="180" />
          <el-table-column prop="body" label="详情" min-width="200" />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.page { padding: 4px 0; }
.toolbar { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.toolbar h2 { margin: 0 0 4px; font-size: 20px; }
.sub { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.stats { margin-bottom: 12px; }
.stat-label { font-size: 12px; color: var(--el-text-color-secondary); }
.stat-val { font-size: 22px; font-weight: 600; margin-top: 4px; }
.config-card { margin-bottom: 12px; }
.vol-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; }
.mono { font-family: ui-monospace, monospace; }
.profit-pos { color: #3dd6c3; }
.profit-neg { color: #f56c6c; }
:deep(.row-flag) { background: rgba(61, 214, 195, 0.08) !important; }
</style>
