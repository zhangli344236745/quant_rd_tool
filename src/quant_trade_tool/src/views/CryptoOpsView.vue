<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { cryptoApi, type PortfolioVarReport } from "@/api/crypto";
import { extractError } from "@/api/http";

const router = useRouter();
const dataDir = "data/crypto";
const logDir = "data/crypto/perp_logs";

const loading = ref(false);
const error = ref("");
const summary = ref<Awaited<ReturnType<typeof cryptoApi.opsSummary>>["data"] | null>(null);
const telemetryDay = ref("");
const telemetryItems = ref<Record<string, unknown>[]>([]);
const autoRefresh = ref(true);
let timer: ReturnType<typeof setInterval> | undefined;

const decisionStats = computed(() => summary.value?.telemetry_summary?.decisions || {});

const decisionBars = computed(() => {
  const stats = decisionStats.value;
  const max = Math.max(1, ...Object.values(stats).map((n) => Number(n) || 0));
  return Object.entries(stats).map(([label, count]) => ({
    label,
    count: Number(count) || 0,
    pct: Math.round(((Number(count) || 0) / max) * 100),
  }));
});

const killSwitch = ref(false);
const webhookUrl = ref("");
const webhookOnError = ref(true);
const webhookOnCb = ref(true);
const controlSaving = ref(false);

const ordersVisible = ref(false);
const ordersBase = ref("");
const ordersLoading = ref(false);
const ordersError = ref("");
const openOrders = ref<Record<string, unknown>[]>([]);
const positionInfo = ref<Record<string, unknown> | null>(null);
const canceling = ref(false);
const cancelAllLoading = ref(false);
const closingLoading = ref(false);
const reconciling = ref(false);
const cancelOrderId = ref("");

const acctLoading = ref(false);
const acctError = ref("");
const acctBalances = ref<{ asset: string; total: number; available?: number | null; used?: number | null }[]>([]);
const acctSummary = ref<Record<string, unknown> | null>(null);
const acctTradeBase = ref("ETH");
const acctTrades = ref<Record<string, unknown>[]>([]);
const acctDaily = ref<{ day: string; realizedPnl: number; funding: number; fees: number; net: number }[]>([]);
const portfolioVar = ref<PortfolioVarReport | null>(null);

function decisionTagType(d: string) {
  if (d === "opened" || d === "flipped") return "success";
  if (d === "error") return "danger";
  if (d === "blocked_circuit_breaker") return "warning";
  return "info";
}

async function openOrderManager(base: string) {
  ordersBase.value = base;
  ordersVisible.value = true;
  positionInfo.value = null;
  await loadOpenOrders();
}

async function loadOpenOrders() {
  if (!ordersBase.value) return;
  ordersLoading.value = true;
  ordersError.value = "";
  try {
    const pos = await cryptoApi.perpPosition({ base: ordersBase.value, testnet: false });
    positionInfo.value = (pos.data as Record<string, unknown>) || null;
    const { data } = await cryptoApi.perpOpenOrders({ base: ordersBase.value, testnet: false });
    openOrders.value = data.items || [];
  } catch (e) {
    ordersError.value = extractError(e);
    positionInfo.value = null;
    openOrders.value = [];
  } finally {
    ordersLoading.value = false;
  }
}

async function cancelOne() {
  if (!ordersBase.value || !cancelOrderId.value.trim()) return;
  canceling.value = true;
  try {
    await cryptoApi.perpCancelOrder({ base: ordersBase.value, order_id: cancelOrderId.value.trim() });
    ElMessage.success("已提交取消");
    cancelOrderId.value = "";
    await loadOpenOrders();
    await refreshAll();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    canceling.value = false;
  }
}

async function cancelAll() {
  if (!ordersBase.value) return;
  cancelAllLoading.value = true;
  try {
    await cryptoApi.perpCancelAllOrders({ base: ordersBase.value });
    ElMessage.success("已提交一键取消挂单");
    await loadOpenOrders();
    await refreshAll();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    cancelAllLoading.value = false;
  }
}

async function closePosition() {
  if (!ordersBase.value) return;
  closingLoading.value = true;
  try {
    await cryptoApi.perpClosePosition({ base: ordersBase.value });
    ElMessage.success("已提交平仓");
    await loadOpenOrders();
    await refreshAll();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    closingLoading.value = false;
  }
}

async function reconcileProtection() {
  if (!ordersBase.value) return;
  reconciling.value = true;
  try {
    await cryptoApi.perpReconcileProtection({ base: ordersBase.value, data_dir: dataDir });
    ElMessage.success("已提交保护单对账/重建（best-effort）");
    await loadOpenOrders();
    await refreshAll();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    reconciling.value = false;
  }
}

async function loadControl() {
  try {
    const { data } = await cryptoApi.opsControlGet();
    killSwitch.value = data.kill_switch;
    webhookUrl.value = data.webhook_url || "";
    webhookOnError.value = data.webhook_on_error !== false;
    webhookOnCb.value = data.webhook_on_circuit_breaker !== false;
  } catch {
    /* optional */
  }
}

async function saveControl() {
  controlSaving.value = true;
  try {
    await cryptoApi.opsControlSave({
      kill_switch: killSwitch.value,
      webhook_url: webhookUrl.value,
      webhook_on_error: webhookOnError.value,
      webhook_on_circuit_breaker: webhookOnCb.value,
    });
    ElMessage.success("运营控制已保存");
    await loadSummary();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    controlSaving.value = false;
  }
}

async function testWebhook() {
  try {
    await cryptoApi.opsTestWebhook();
    ElMessage.success("测试 Webhook 已发送");
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function loadSummary() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await cryptoApi.opsSummary({ data_dir: dataDir, log_dir: logDir });
    summary.value = data;
    if (data.control) {
      killSwitch.value = data.control.kill_switch;
      webhookUrl.value = data.control.webhook_url || "";
      webhookOnError.value = data.control.webhook_on_error !== false;
      webhookOnCb.value = data.control.webhook_on_circuit_breaker !== false;
    }
    if (!telemetryDay.value && data.telemetry_days?.length) {
      telemetryDay.value = data.telemetry_days[0];
    }
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

async function loadTelemetry() {
  try {
    const { data } = await cryptoApi.perpTelemetry({
      log_dir: logDir,
      day: telemetryDay.value || undefined,
      limit: 120,
    });
    telemetryItems.value = [...data.items].reverse();
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function refreshAll() {
  await loadSummary();
  await loadTelemetry();
  await loadAccountPanel();
}

async function loadAccountPanel() {
  acctLoading.value = true;
  acctError.value = "";
  portfolioVar.value = null;
  try {
    const [b, t, p] = await Promise.all([
      cryptoApi.perpAccountBalances({ testnet: false }),
      cryptoApi.perpAccountTrades({ base: acctTradeBase.value, limit: 20, testnet: false }),
      cryptoApi.perpAccountDailyPnl({ days: 7, testnet: false }),
    ]);
    acctBalances.value = b.data.items || [];
    acctSummary.value = (b.data.summary as Record<string, unknown>) || null;
    acctTrades.value = (t.data.items as Record<string, unknown>[]) || [];
    acctDaily.value = p.data.items || [];
    if ((b.data as any).error) acctError.value = String((b.data as any).error);
    if ((t.data as any).error && !acctError.value) acctError.value = String((t.data as any).error);
    if ((p.data as any).error && !acctError.value) acctError.value = String((p.data as any).error);
    if (b.data.enabled) {
      try {
        const { data } = await cryptoApi.varPortfolio({
          testnet: false,
          confidence: "0.99",
          lookback_bars: 252,
          horizon_days: 1,
        });
        portfolioVar.value = data;
      } catch {
        portfolioVar.value = null;
      }
    }
  } catch (e) {
    acctError.value = extractError(e);
  } finally {
    acctLoading.value = false;
  }
}

const portfolioVar99Usdt = () => portfolioVar.value?.metrics?.["0.99"]?.var_usdt;

async function reloadTrades() {
  try {
    const { data } = await cryptoApi.perpAccountTrades({ base: acctTradeBase.value, limit: 20, testnet: false });
    acctTrades.value = (data.items as Record<string, unknown>[]) || [];
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function quickSignalOnly(base: string) {
  try {
    await cryptoApi.perpBotRun({
      base,
      quote: "USDT",
      timeframe: "5m",
      ohlcv_limit: 800,
      leverage: 3,
      usdt_risk_fraction: 0.2,
      min_notional_usdt: 10,
      max_daily_loss_pct: 0.03,
      sl_pct: 0.01,
      tp_pct: 0.015,
      sizing_mode: "hybrid",
      atr_period: 14,
      sl_atr: 1.5,
      tp_atr: 2.5,
      use_atr_sl_tp: true,
      max_protection_failures: 3,
      dry_run: true,
      testnet: false,
      signal_only: true,
    });
    ElMessage.success(`${base} signal-only 已执行`);
    await refreshAll();
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

onMounted(async () => {
  await loadControl();
  await refreshAll();
  timer = setInterval(() => {
    if (autoRefresh.value) refreshAll();
  }, 15000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div>
    <h1 class="page-title">Crypto 运营看板</h1>
    <p class="page-desc">永续状态、定时调度与 JSONL 遥测 — 本地只读汇总，默认 15s 自动刷新。</p>

    <div class="toolbar">
      <el-button type="primary" :loading="loading" @click="refreshAll">刷新</el-button>
      <el-switch v-model="autoRefresh" active-text="自动刷新" />
      <el-select v-model="telemetryDay" placeholder="日志日期" style="width: 140px" @change="loadTelemetry">
        <el-option v-for="d in summary?.telemetry_days || []" :key="d" :label="d" :value="d" />
      </el-select>
      <el-button @click="router.push('/schedules')">管理调度</el-button>
      <el-button @click="router.push('/perp-bot')">永续 Bot</el-button>
      <el-button @click="router.push('/perp-portfolio')">组合永续</el-button>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-card shadow="never" class="panel-card mb">
      <template #header>运营控制</template>
      <div class="control-row">
        <el-switch
          v-model="killSwitch"
          active-text="Kill Switch（阻止实盘下单）"
          inactive-text="实盘允许"
          inline-prompt
        />
        <el-button type="danger" :loading="controlSaving" @click="saveControl">保存控制</el-button>
      </div>
      <div class="control-row mt">
        <el-input v-model="webhookUrl" placeholder="Webhook URL（Slack/Discord/自建）" clearable style="max-width: 420px" />
        <el-checkbox v-model="webhookOnError">错误告警</el-checkbox>
        <el-checkbox v-model="webhookOnCb">熔断告警</el-checkbox>
        <el-button @click="testWebhook">测试 Webhook</el-button>
      </div>
      <el-alert
        v-if="killSwitch"
        type="warning"
        title="Kill Switch 已开启：非 dry-run 的永续/组合 Bot 将跳过交易所下单"
        show-icon
        :closable="false"
        class="mt"
      />
    </el-card>

    <el-row v-if="summary" :gutter="16" class="mb">
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">调度任务</div>
          <div class="stat-val">{{ summary.schedules.running }} / {{ summary.schedules.total }} 运行中</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">遥测事件（当前窗口）</div>
          <div class="stat-val">{{ summary.telemetry_summary.total }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">熔断拦截</div>
          <div class="stat-val warn">{{ summary.telemetry_summary.circuit_breaker_blocks }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">错误记录</div>
          <div class="stat-val">{{ summary.telemetry_summary.error_count }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="panel-card mb" v-loading="acctLoading">
      <template #header>账户概览（永续）</template>
      <el-alert v-if="acctError" type="warning" :title="acctError" show-icon class="mb" />

      <el-row :gutter="16">
        <el-col :span="6">
          <div class="stat-label">USDT 总资产</div>
          <div class="stat-val">
            {{ (acctBalances.find((b) => b.asset === "USDT")?.total ?? 0).toFixed(2) }}
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-label">USDT 可用</div>
          <div class="stat-val">
            {{ (acctBalances.find((b) => b.asset === "USDT")?.available ?? 0).toFixed(2) }}
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-label">未实现盈亏（合计）</div>
          <div class="stat-val">
            {{ Number(acctSummary?.totalUnrealizedProfit ?? 0).toFixed(2) }}
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-label">组合 1 日 99% VaR</div>
          <div v-if="portfolioVar?.enabled && portfolioVar.metrics" class="stat-val warn">
            {{ portfolioVar99Usdt()?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "—" }} USDT
          </div>
          <div v-else-if="portfolioVar && !portfolioVar.enabled" class="muted small">
            {{ portfolioVar.error || "未配置 API" }}
          </div>
          <div v-else class="muted small">—</div>
          <router-link
            v-if="portfolioVar?.enabled"
            to="/crypto-var?tab=portfolio"
            class="var-link"
          >
            风险 VaR 详情 →
          </router-link>
        </el-col>
      </el-row>

      <el-row :gutter="16" class="mt">
        <el-col :span="10">
          <el-card shadow="never" class="panel-card">
            <template #header>余额</template>
            <el-table :data="acctBalances" size="small" max-height="220" stripe>
              <el-table-column prop="asset" label="资产" width="90" />
              <el-table-column prop="total" label="总额" width="110">
                <template #default="{ row }">{{ Number(row.total).toFixed(6) }}</template>
              </el-table-column>
              <el-table-column prop="available" label="可用" width="110">
                <template #default="{ row }">{{ row.available != null ? Number(row.available).toFixed(6) : "—" }}</template>
              </el-table-column>
              <el-table-column prop="used" label="占用" width="110">
                <template #default="{ row }">{{ row.used != null ? Number(row.used).toFixed(6) : "—" }}</template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="14">
          <el-card shadow="never" class="panel-card">
            <template #header>
              <div class="toolbar" style="margin-bottom: 0">
                <span>最近交易</span>
                <el-select v-model="acctTradeBase" style="width: 120px" @change="reloadTrades">
                  <el-option label="ETH" value="ETH" />
                  <el-option label="BTC" value="BTC" />
                </el-select>
              </div>
            </template>
            <el-table :data="acctTrades" size="small" max-height="220" stripe>
              <el-table-column prop="ts" label="时间" width="180" show-overflow-tooltip />
              <el-table-column prop="symbol" label="合约" width="120" />
              <el-table-column prop="side" label="方向" width="70" />
              <el-table-column prop="price" label="价格" width="100" />
              <el-table-column prop="qty" label="数量" width="90" />
              <el-table-column prop="fee" label="手续费" width="90" />
              <el-table-column prop="orderId" label="orderId" min-width="140" show-overflow-tooltip />
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="never" class="panel-card mt">
        <template #header>每日盈亏（近 7 日）</template>
        <el-table :data="acctDaily" size="small" stripe max-height="200">
          <el-table-column prop="day" label="日期" width="120" />
          <el-table-column prop="realizedPnl" label="Realized" width="120" />
          <el-table-column prop="funding" label="Funding" width="120" />
          <el-table-column prop="fees" label="Fees" width="120" />
          <el-table-column prop="net" label="Net" width="120" />
        </el-table>
      </el-card>
    </el-card>

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <template #header>永续状态文件</template>
          <el-empty v-if="!summary?.perp_states?.length" description="暂无 perp_state_*.json" />
          <div v-for="st in summary?.perp_states || []" :key="String(st.base)" class="state-card">
            <div class="state-head">
              <strong>{{ st.base }}</strong>
              <el-tag size="small" type="info">{{ (st.position as { side?: string })?.side || "flat" }}</el-tag>
            </div>
            <div class="mono muted small">bar {{ st.last_seen_bar_end || "—" }} · target {{ st.last_target_side || "—" }}</div>
            <div v-if="st.protection" class="small mt">
              保护 streak {{ (st.protection as Record<string, unknown>).protection_fail_streak ?? 0 }}
              · soft {{ (st.protection as Record<string, unknown>).soft_protection_active ? "ON" : "off" }}
            </div>
            <div class="mt state-actions">
              <el-button size="small" @click="quickSignalOnly(String(st.base))">Signal-only 一轮</el-button>
              <el-button size="small" @click="openOrderManager(String(st.base))">订单管理</el-button>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="panel-card mt">
          <template #header>决策分布</template>
          <div v-for="bar in decisionBars" :key="bar.label" class="bar-row">
            <span class="bar-label mono">{{ bar.label }}</span>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: bar.pct + '%' }" />
            </div>
            <span class="bar-count">{{ bar.count }}</span>
          </div>
          <el-empty v-if="!decisionBars.length" description="暂无决策统计" />
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card shadow="never" class="panel-card">
          <template #header>遥测日志（最新在上）</template>
          <el-table :data="telemetryItems" size="small" max-height="520" stripe empty-text="今日暂无 JSONL">
            <el-table-column prop="ts" label="时间" width="180" show-overflow-tooltip />
            <el-table-column prop="base" label="标的" width="64" />
            <el-table-column label="决策" width="140">
              <template #default="{ row }">
                <el-tag size="small" :type="decisionTagType(String(row.decision))">{{ row.decision }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="perp_action" label="动作" width="72" />
            <el-table-column prop="signal_action" label="信号" width="72" />
            <el-table-column prop="message" label="说明" min-width="160" show-overflow-tooltip />
            <el-table-column prop="error_category" label="错误类" width="100" />
          </el-table>
        </el-card>

        <el-card v-if="summary?.schedule_alert_recent?.length" shadow="never" class="panel-card mt">
          <template #header>调度告警（最近）</template>
          <el-table :data="summary.schedule_alert_recent" size="small" max-height="160">
            <el-table-column prop="ts" label="时间" width="170" show-overflow-tooltip />
            <el-table-column prop="job_id" label="任务" width="110" />
            <el-table-column prop="rule" label="规则" width="130" />
            <el-table-column prop="message" label="说明" min-width="160" show-overflow-tooltip />
          </el-table>
          <el-button link type="primary" class="mt" @click="router.push('/schedules')">配置规则 →</el-button>
        </el-card>

        <el-card shadow="never" class="panel-card mt">
          <template #header>调度任务</template>
          <el-table :data="summary?.schedules?.jobs || []" size="small" max-height="200">
            <el-table-column prop="id" label="ID" width="120" />
            <el-table-column prop="name" label="名称" min-width="120" />
            <el-table-column prop="status" label="状态" width="90" />
            <el-table-column prop="run_count" label="次数" width="70" />
            <el-table-column prop="last_run_at" label="上次运行" min-width="160" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="ordersVisible" :title="`订单管理 · ${ordersBase}`" width="860px">
      <el-alert v-if="ordersError" type="error" :title="ordersError" show-icon class="mb" />
      <div class="toolbar">
        <el-button :loading="ordersLoading" @click="loadOpenOrders">刷新 open orders</el-button>
        <el-button type="warning" :loading="cancelAllLoading" @click="cancelAll">一键取消挂单</el-button>
        <el-button type="danger" :loading="closingLoading" @click="closePosition">一键平仓（reduceOnly 市价）</el-button>
        <el-button :loading="reconciling" @click="reconcileProtection">保护单对账/重建</el-button>
      </div>
      <div class="toolbar mt">
        <el-input v-model="cancelOrderId" placeholder="order id / clientOrderId" style="max-width: 280px" />
        <el-button type="warning" :loading="canceling" @click="cancelOne">取消单笔</el-button>
        <span class="muted small">提示：Kill Switch 开启时禁止变更类操作（取消/平仓/对账）。</span>
      </div>

      <el-card shadow="never" class="panel-card mb">
        <template #header>当前持仓（交易所）</template>
        <el-descriptions v-if="positionInfo?.position" :column="4" size="small" border>
          <el-descriptions-item label="symbol">{{ positionInfo.symbol }}</el-descriptions-item>
          <el-descriptions-item label="side">{{ (positionInfo.position as any).side }}</el-descriptions-item>
          <el-descriptions-item label="contracts">{{ (positionInfo.position as any).contracts }}</el-descriptions-item>
          <el-descriptions-item label="uPnL">{{ (positionInfo.position as any).unrealized_pnl ?? "—" }}</el-descriptions-item>
        </el-descriptions>
        <p v-else class="muted small">
          {{
            positionInfo?.error
              ? `无法读取持仓：${positionInfo.error}`
              : "无持仓或 fetch_positions 不可用"
          }}
        </p>
      </el-card>

      <el-table :data="openOrders" size="small" stripe max-height="420" v-loading="ordersLoading">
        <el-table-column prop="id" label="id" width="120" show-overflow-tooltip />
        <el-table-column prop="clientOrderId" label="client" width="140" show-overflow-tooltip />
        <el-table-column prop="type" label="type" width="130" />
        <el-table-column prop="side" label="side" width="70" />
        <el-table-column prop="amount" label="amt" width="80" />
        <el-table-column prop="price" label="price" width="90" />
        <el-table-column prop="stopPrice" label="stop" width="90" />
        <el-table-column prop="status" label="status" width="90" />
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}
.mb {
  margin-bottom: 16px;
}
.mt {
  margin-top: 12px;
}
.stat-card {
  text-align: center;
}
.stat-label {
  font-size: 12px;
  color: var(--text-muted);
}
.stat-val {
  font-size: 1.4rem;
  font-weight: 700;
  margin-top: 6px;
}
.stat-val.warn {
  color: #e6a23c;
}
.var-link {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-color-primary);
  text-decoration: none;
}
.var-link:hover {
  text-decoration: underline;
}
.state-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
}
.state-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.small {
  font-size: 12px;
}
.muted {
  color: var(--text-muted);
}
.control-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12px;
}
.bar-label {
  width: 140px;
  flex-shrink: 0;
}
.bar-track {
  flex: 1;
  height: 8px;
  background: var(--border);
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  background: var(--el-color-primary);
  border-radius: 4px;
  min-width: 2px;
}
.bar-count {
  width: 28px;
  text-align: right;
  color: var(--text-muted);
}
.state-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
