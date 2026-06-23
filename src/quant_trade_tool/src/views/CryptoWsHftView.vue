<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  cryptoApi,
  type HftEvent,
  type HftStrategy,
  type WsHftBotStatusDetail,
} from "@/api/crypto";
import { extractError } from "@/api/http";

const loading = ref(false);
const running = ref(false);
const strategies = ref<HftStrategy[]>([]);
const events = ref<HftEvent[]>([]);
const status = ref<WsHftBotStatusDetail | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const form = reactive({
  bot_id: "btc-ws-mm",
  symbol: "BTC",
  market_type: "future",
  strategy_id: "classic_mm",
  testnet: true,
  dry_run: true,
  trigger_mode: "throttle" as "every_update" | "throttle",
  throttle_ms: 20,
  max_session_loss_usdt: 0,
  max_inventory_usdt: 0,
});

const strategyParamsMap = reactive<Record<string, number>>({});

const currentStrategy = computed(() =>
  strategies.value.find((s) => s.id === form.strategy_id),
);

function resetStrategyParams(strategy?: HftStrategy | null) {
  if (!strategy) return;
  for (const key of Object.keys(strategyParamsMap)) delete strategyParamsMap[key];
  for (const field of strategy.param_schema) {
    const name = String(field.name);
    strategyParamsMap[name] = Number(field.default ?? strategy.default_params[name] ?? 0);
  }
}

watch(() => form.strategy_id, () => resetStrategyParams(currentStrategy.value));
watch(strategies, () => resetStrategyParams(currentStrategy.value));

const strategyParams = computed(() => {
  const out: Record<string, number> = {};
  for (const field of currentStrategy.value?.param_schema ?? []) {
    const name = String(field.name);
    out[name] = strategyParamsMap[name] ?? Number(field.default ?? 0);
  }
  return out;
});

const pnlState = computed(() => (status.value?.state?.pnl ?? {}) as Record<string, number>);
const riskState = computed(() => (status.value?.state?.risk ?? {}) as Record<string, unknown>);

const latency = computed(() => status.value?.state?.latency_us);

function num(v: number | undefined | null, d = 4) {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
}

async function loadMeta() {
  loading.value = true;
  try {
    const sRes = await cryptoApi.wsHftStrategies();
    strategies.value = sRes.data ?? [];
    await refreshStatus();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

async function refreshStatus() {
  try {
    const { data } = await cryptoApi.wsHftBotStatus(form.bot_id);
    status.value = data;
    const ev = await cryptoApi.wsHftBotEvents(form.bot_id, 30);
    events.value = ev.data?.items ?? [];
  } catch {
    status.value = null;
    events.value = [];
  }
}

async function saveBot() {
  running.value = true;
  try {
    await cryptoApi.wsHftUpsertBot({
      bot_id: form.bot_id,
      symbol: form.symbol,
      market_type: form.market_type,
      strategy_id: form.strategy_id,
      strategy_params: strategyParams.value,
      testnet: form.testnet,
      dry_run: form.dry_run,
      trigger_mode: form.trigger_mode,
      throttle_ms: form.throttle_ms,
      max_session_loss_usdt: form.max_session_loss_usdt,
      max_inventory_usdt: form.max_inventory_usdt,
    });
    ElMessage.success("Bot 已保存");
    await refreshStatus();
    return true;
  } catch (e) {
    ElMessage.error(extractError(e));
    return false;
  } finally {
    running.value = false;
  }
}

async function ensureRegistered() {
  if (status.value?.registered !== false && status.value?.config) return true;
  ElMessage.info("首次启动将自动保存 Bot 配置");
  return saveBot();
}

async function startBot() {
  if (!form.dry_run) {
    try {
      await ElMessageBox.confirm("即将开启实盘下单（非观测模式），确认继续？", "实盘警告", {
        type: "warning",
      });
    } catch {
      return;
    }
  }
  if (!form.testnet && !form.dry_run) {
    try {
      await ElMessageBox.confirm("主网实盘做市，确认继续？", "主网警告", { type: "warning" });
    } catch {
      return;
    }
  }
  if (!(await ensureRegistered())) return;
  running.value = true;
  try {
    const { data } = await cryptoApi.wsHftStartBot(form.bot_id, {
      confirm_live: !form.dry_run,
      confirm_mainnet: !form.testnet,
    });
    status.value = data;
    ElMessage.success(form.dry_run ? "观测模式已启动" : "做市已启动");
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    running.value = false;
  }
}

async function stopBot() {
  running.value = true;
  try {
    const { data } = await cryptoApi.wsHftStopBot(form.bot_id, true);
    status.value = data;
    ElMessage.success("已停止并尝试撤单");
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    running.value = false;
  }
}

onMounted(() => {
  loadMeta();
  pollTimer = setInterval(refreshStatus, 3000);
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<template>
  <div class="page">
    <header class="head">
      <div>
        <h1>WS 做市</h1>
        <p class="sub">WebSocket 事件驱动做市 · 经典 / 网格 / 波动率 / 失衡 / AS · 默认观测模式</p>
      </div>
      <el-button :loading="loading" @click="loadMeta">刷新</el-button>
    </header>

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never" v-loading="loading">
          <template #header>Bot 配置</template>
          <el-form label-width="120px">
            <el-form-item label="Bot ID">
              <el-input v-model="form.bot_id" />
            </el-form-item>
            <el-form-item label="标的">
              <el-input v-model="form.symbol" style="width: 100px" />
              <el-select v-model="form.market_type" style="width: 120px; margin-left: 8px">
                <el-option label="永续" value="future" />
                <el-option label="现货" value="spot" />
              </el-select>
            </el-form-item>
            <el-form-item label="策略">
              <el-select v-model="form.strategy_id" style="width: 100%">
                <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
              </el-select>
              <p v-if="currentStrategy?.description" class="hint">{{ currentStrategy.description }}</p>
            </el-form-item>
            <el-form-item
              v-for="field in currentStrategy?.param_schema ?? []"
              :key="String(field.name)"
              :label="String(field.label ?? field.name)"
            >
              <el-input-number
                v-model="strategyParamsMap[String(field.name)]"
                :min="Number(field.min ?? 0)"
                :max="Number(field.max ?? 99999)"
                :step="field.type === 'int' ? 1 : 0.1"
              />
            </el-form-item>
            <el-form-item label="触发模式">
              <el-select v-model="form.trigger_mode" style="width: 100%">
                <el-option label="每次 depth 更新" value="every_update" />
                <el-option label="节流" value="throttle" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="form.trigger_mode === 'throttle'" label="节流 ms">
              <el-input-number v-model="form.throttle_ms" :min="1" :max="500" />
            </el-form-item>
            <el-form-item label="会话止损 USDT">
              <el-input-number v-model="form.max_session_loss_usdt" :min="0" :max="100000" :step="10" />
              <p class="hint">0 = 不启用</p>
            </el-form-item>
            <el-form-item label="库存上限 USDT">
              <el-input-number v-model="form.max_inventory_usdt" :min="0" :max="100000" :step="50" />
              <p class="hint">0 = 使用策略参数</p>
            </el-form-item>
            <el-form-item label="观测模式">
              <el-switch v-model="form.dry_run" active-text="仅观测" inactive-text="可实盘" />
            </el-form-item>
            <el-form-item label="Testnet">
              <el-switch v-model="form.testnet" />
            </el-form-item>
            <el-form-item>
              <el-button @click="saveBot" :loading="running">保存</el-button>
              <el-button type="primary" @click="startBot" :loading="running">启动</el-button>
              <el-button @click="stopBot" :loading="running">停止</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card shadow="never" class="mb">
          <template #header>状态与延迟</template>
          <p v-if="status?.running">
            <el-tag type="success">运行中</el-tag>
            <el-tag v-if="status.live_trading" type="danger" class="ml">实盘下单</el-tag>
            <el-tag v-else type="info" class="ml">观测</el-tag>
          </p>
          <p v-else-if="riskState.halted"><el-tag type="danger">风控熔断</el-tag> {{ riskState.halt_reason }}</p>
          <p v-else-if="status?.registered === false">
            <el-tag type="warning">未保存</el-tag> 请先保存或点启动自动保存
          </p>
          <p v-else><el-tag type="info">已停止</el-tag></p>
          <el-descriptions :column="2" size="small" class="mt">
            <el-descriptions-item label="会话 PnL">{{ num(pnlState.session_usdt, 2) }}</el-descriptions-item>
            <el-descriptions-item label="当日 PnL">{{ num(pnlState.daily_usdt, 2) }}</el-descriptions-item>
            <el-descriptions-item label="总 PnL">{{ num(pnlState.total_usdt, 2) }}</el-descriptions-item>
            <el-descriptions-item label="已实现">{{ num(pnlState.realized_usdt, 2) }}</el-descriptions-item>
            <el-descriptions-item label="未实现">{{ num(pnlState.unrealized_usdt, 2) }}</el-descriptions-item>
            <el-descriptions-item label="成交笔数">{{ pnlState.fill_count ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="Mid">{{ num(status?.state?.last_mid as number) }}</el-descriptions-item>
            <el-descriptions-item label="库存 USDT">{{ num(status?.state?.inventory_usdt as number) }}</el-descriptions-item>
            <el-descriptions-item label="Book 更新">{{ status?.state?.book_updates_total ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="Reconcile">{{ status?.state?.reconciles_total ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="节流跳过">{{ status?.state?.throttled_skips ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="错误">{{ status?.last_error || "—" }}</el-descriptions-item>
            <el-descriptions-item label="延迟 last μs">{{ num(latency?.last, 0) }}</el-descriptions-item>
            <el-descriptions-item label="p50 / p95 μs">
              {{ num(latency?.p50, 0) }} / {{ num(latency?.p95, 0) }}
            </el-descriptions-item>
            <el-descriptions-item label="拒交叉">{{ status?.state?.execution_stats?.rejected_cross ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="WS 重连">{{ status?.state?.execution_stats?.reconnects ?? 0 }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <el-card shadow="never">
          <template #header>事件流</template>
          <el-table :data="events" size="small" stripe max-height="360">
            <el-table-column prop="ts" label="时间" width="180" />
            <el-table-column prop="type" label="类型" width="120" />
            <el-table-column label="详情">
              <template #default="{ row }">{{ JSON.stringify(row).slice(0, 120) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page { padding: 16px 20px 32px; }
.head { display: flex; justify-content: space-between; margin-bottom: 16px; }
.head h1 { margin: 0 0 6px; font-size: 22px; }
.sub { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
.hint { margin: 6px 0 0; font-size: 12px; color: var(--el-text-color-secondary); }
.mb { margin-bottom: 16px; }
.mt { margin-top: 12px; }
.ml { margin-left: 8px; }
</style>
