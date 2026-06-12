<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { cryptoApi, type PerpBotRequest } from "@/api/crypto";
import { extractError } from "@/api/http";
import ResultPanel from "@/components/ResultPanel.vue";
import SignalSummary from "@/components/SignalSummary.vue";
import { useNotify } from "@/composables/useNotify";

const notify = useNotify();

const form = reactive<PerpBotRequest>({
  base: "BTC",
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
  signal_only: false,
});

const loading = ref(false);
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");

const scheduler = reactive({
  interval_minutes: 10,
  bots: [] as any[],
  loading: false,
});

async function submit() {
  loading.value = true;
  error.value = "";
  result.value = null;
  try {
    const { data } = await cryptoApi.perpBotRun({ ...form });
    result.value = data;
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

async function loadScheduler() {
  scheduler.loading = true;
  try {
    const { data } = await cryptoApi.botSchedulerStatus();
    scheduler.bots = ((data as any).bots ?? []).filter((b: any) => b.kind === "perp");
  } catch (e) {
    notify.error("加载调度失败", extractError(e));
  } finally {
    scheduler.loading = false;
  }
}

async function registerSchedule() {
  try {
    await cryptoApi.botSchedulerRegister({
      kind: "perp",
      interval_minutes: scheduler.interval_minutes,
      perp: { ...form },
    });
    notify.success("永续 Bot 已登记", "可点击启动");
    await loadScheduler();
  } catch (e) {
    notify.error("登记失败", extractError(e));
  }
}

async function startBot(id: string) {
  try {
    await cryptoApi.botSchedulerStart(id);
    notify.success("Bot 已启动", id);
    await loadScheduler();
  } catch (e) {
    notify.error("启动失败", extractError(e));
  }
}
async function stopBot(id: string) {
  try {
    await cryptoApi.botSchedulerStop(id);
    notify.info("Bot 已停止", id);
    await loadScheduler();
  } catch (e) {
    notify.error("停止失败", extractError(e));
  }
}
async function removeBot(id: string) {
  try {
    await cryptoApi.botSchedulerRemove(id);
    notify.success("已删除", id);
    await loadScheduler();
  } catch (e) {
    notify.error("删除失败", extractError(e));
  }
}

onMounted(loadScheduler);
</script>

<template>
  <div>
    <h1 class="page-title">永续 Bot</h1>
    <p class="page-desc">
      /crypto/perp-bot/run — ATR 定仓、熔断、原生/软保护、JSONL 遥测；支持自动调度托管。
    </p>

    <el-row :gutter="20">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <el-form label-width="120px" size="small">
            <el-divider content-position="left">标的</el-divider>
            <el-form-item label="Base">
              <el-select v-model="form.base"><el-option label="BTC" value="BTC" /><el-option label="ETH" value="ETH" /></el-select>
            </el-form-item>
            <el-form-item label="周期"><el-input v-model="form.timeframe" /></el-form-item>
            <el-form-item label="杠杆"><el-input-number v-model="form.leverage" :min="1" :max="20" /></el-form-item>

            <el-divider content-position="left">风控</el-divider>
            <el-form-item label="定仓模式">
              <el-select v-model="form.sizing_mode">
                <el-option label="hybrid" value="hybrid" />
                <el-option label="atr" value="atr" />
                <el-option label="leverage_fraction" value="leverage_fraction" />
              </el-select>
            </el-form-item>
            <el-form-item label="风险占比"><el-input-number v-model="form.usdt_risk_fraction" :min="0.01" :max="1" :step="0.05" /></el-form-item>
            <el-form-item label="SL ATR"><el-input-number v-model="form.sl_atr" :min="0.5" :step="0.1" /></el-form-item>
            <el-form-item label="TP ATR"><el-input-number v-model="form.tp_atr" :min="0.5" :step="0.1" /></el-form-item>
            <el-form-item label="日内熔断"><el-input-number v-model="form.max_daily_loss_pct" :min="0" :max="0.5" :step="0.01" /></el-form-item>
            <el-form-item label="ATR 保护单"><el-switch v-model="form.use_atr_sl_tp" /></el-form-item>

            <el-divider content-position="left">执行</el-divider>
            <el-form-item label="Dry-run"><el-switch v-model="form.dry_run" /></el-form-item>
            <el-form-item label="测试网"><el-switch v-model="form.testnet" /></el-form-item>
            <el-form-item label="仅信号"><el-switch v-model="form.signal_only" /></el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="loading" @click="submit">运行一轮</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card v-if="result?.signal" shadow="never" class="panel-card">
          <template #header>
            <span>信号</span>
            <el-tag v-if="result.decision" class="ml" size="small">{{ result.decision }}</el-tag>
          </template>
          <SignalSummary :signal="result.signal as Record<string, unknown>" />
          <div v-if="result.sizing" class="sizing mono">
            名义 {{ (result.sizing as any).notional_usdt }} USDT · mode {{ (result.sizing as any).mode }}
          </div>
        </el-card>
        <el-card shadow="never" class="panel-card" style="margin-bottom: 12px">
          <template #header>
            <span>自动调度</span>
          </template>
          <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 10px">
            <span>间隔（分钟）</span>
            <el-input-number v-model="scheduler.interval_minutes" :min="1" size="small" />
            <el-button type="primary" size="small" @click="registerSchedule">
              登记当前配置
            </el-button>
            <el-button size="small" :loading="scheduler.loading" @click="loadScheduler">
              刷新
            </el-button>
          </div>
          <el-table :data="scheduler.bots" size="small">
            <el-table-column prop="bot_id" label="Bot" />
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag
                  :type="row.status === 'running' ? 'success' : row.status === 'error' ? 'danger' : 'info'"
                  size="small"
                >
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="interval_minutes" label="间隔" width="70" />
            <el-table-column prop="run_count" label="运行" width="70" />
            <el-table-column prop="last_error" label="最近错误" show-overflow-tooltip />
            <el-table-column label="操作" width="180">
              <template #default="{ row }">
                <el-button
                  v-if="row.status !== 'running'"
                  size="small"
                  type="success"
                  @click="startBot(row.bot_id)"
                >
                  启动
                </el-button>
                <el-button v-else size="small" type="warning" @click="stopBot(row.bot_id)">
                  停止
                </el-button>
                <el-button size="small" type="danger" plain @click="removeBot(row.bot_id)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
        <ResultPanel :loading="loading" :result="result" :error="error" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.ml {
  margin-left: 8px;
}
.sizing {
  margin-top: 8px;
  font-size: 12px;
  color: var(--accent);
}
</style>
