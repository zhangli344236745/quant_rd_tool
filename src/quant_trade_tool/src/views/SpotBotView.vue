<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { cryptoApi } from "@/api/crypto";
import { extractError } from "@/api/http";
import EquityCurveChart from "@/components/EquityCurveChart.vue";
import ResultPanel from "@/components/ResultPanel.vue";
import SignalSummary from "@/components/SignalSummary.vue";
import { useNotify } from "@/composables/useNotify";

const notify = useNotify();

const form = reactive({
  symbol: "BTC",
  quote: "USDT",
  quote_amount: 50,
  timeframe: "1d",
  dry_run: true,
  testnet: false,
  signal_only: false,
  // risk / sizing
  sizing_mode: "hybrid",
  risk_fraction: 0.5,
  min_signal_confidence: 0,
  use_atr_sl_tp: true,
  sl_pct: 0.03,
  tp_pct: 0.06,
  sl_atr: 1.5,
  tp_atr: 2.5,
  // signal enhancement
  use_enhanced_signal: true,
  require_htf_confirm: true,
  require_volume_confirm: false,
  min_atr_pct: 0,
  max_atr_pct: 0,
  volume_min_ratio: 1,
  // paper
  paper_mode: false,
  paper_initial_cash: 10000,
  fee_pct: 0.001,
  slippage_pct: 0.0005,
});

const loading = ref(false);
const result = ref<unknown>(null);
const error = ref("");

const perf = ref<any>(null);
const scheduler = reactive({
  interval_minutes: 60,
  bots: [] as any[],
  loading: false,
});

async function submit() {
  loading.value = true;
  error.value = "";
  result.value = null;
  try {
    const { data } = await cryptoApi.spotBotRun({ ...form });
    result.value = data;
    if (form.paper_mode) await loadPerformance();
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

async function loadPerformance() {
  try {
    const { data } = await cryptoApi.spotBotPaperPerformance({
      symbol: form.symbol,
      quote: form.quote,
      paper_initial_cash: form.paper_initial_cash,
    });
    perf.value = data;
  } catch (e) {
    notify.error("加载绩效失败", extractError(e));
  }
}

async function resetPaper() {
  try {
    await cryptoApi.spotBotPaperReset({ ...form });
    perf.value = null;
    notify.success("纸面账户已重置");
  } catch (e) {
    notify.error("重置失败", extractError(e));
  }
}

async function loadScheduler() {
  scheduler.loading = true;
  try {
    const { data } = await cryptoApi.botSchedulerStatus();
    scheduler.bots = ((data as any).bots ?? []).filter((b: any) => b.kind === "spot");
  } catch (e) {
    notify.error("加载调度失败", extractError(e));
  } finally {
    scheduler.loading = false;
  }
}

async function registerSchedule() {
  try {
    await cryptoApi.botSchedulerRegister({
      kind: "spot",
      interval_minutes: scheduler.interval_minutes,
      spot: { ...form },
    });
    notify.success("已登记", "可点击启动");
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

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(2)}%`;
}

const equityChartData = computed(() => {
  const curve = perf.value?.equity_curve ?? [];
  return curve.map((p: { ts: string; equity: number }) => ({
    time: p.ts,
    value: p.equity,
  }));
});

onMounted(loadScheduler);
</script>

<template>
  <div>
    <h1 class="page-title">现货 Bot</h1>
    <p class="page-desc">
      /crypto/bot/run — 币安现货。多周期信号确认 + ATR 风险仓位 + 软性止损止盈 + 纸面交易/自动调度。默认 dry-run。
    </p>

    <el-row :gutter="20">
      <el-col :span="9">
        <el-card shadow="never" class="panel-card">
          <el-form label-width="120px" size="small">
            <el-divider content-position="left">基础</el-divider>
            <el-form-item label="标的"><el-input v-model="form.symbol" /></el-form-item>
            <el-form-item label="计价"><el-input v-model="form.quote" /></el-form-item>
            <el-form-item label="单笔预算 USDT">
              <el-input-number v-model="form.quote_amount" :min="5" />
            </el-form-item>
            <el-form-item label="周期"><el-input v-model="form.timeframe" /></el-form-item>
            <el-form-item label="Dry-run"><el-switch v-model="form.dry_run" /></el-form-item>
            <el-form-item label="测试网"><el-switch v-model="form.testnet" /></el-form-item>
            <el-form-item label="仅信号"><el-switch v-model="form.signal_only" /></el-form-item>

            <el-divider content-position="left">信号增强</el-divider>
            <el-form-item label="多周期/过滤">
              <el-switch v-model="form.use_enhanced_signal" />
            </el-form-item>
            <el-form-item label="高周期确认">
              <el-switch v-model="form.require_htf_confirm" :disabled="!form.use_enhanced_signal" />
            </el-form-item>
            <el-form-item label="成交量确认">
              <el-switch v-model="form.require_volume_confirm" :disabled="!form.use_enhanced_signal" />
            </el-form-item>
            <el-form-item label="ATR% 下限">
              <el-input-number v-model="form.min_atr_pct" :min="0" :step="0.001" :precision="4" />
            </el-form-item>
            <el-form-item label="ATR% 上限">
              <el-input-number v-model="form.max_atr_pct" :min="0" :step="0.001" :precision="4" />
            </el-form-item>

            <el-divider content-position="left">风险与仓位</el-divider>
            <el-form-item label="仓位模式">
              <el-select v-model="form.sizing_mode">
                <el-option label="固定比例" value="fixed" />
                <el-option label="ATR 风险" value="atr" />
                <el-option label="混合 (取小)" value="hybrid" />
              </el-select>
            </el-form-item>
            <el-form-item label="风险比例">
              <el-input-number v-model="form.risk_fraction" :min="0.05" :max="1" :step="0.05" />
            </el-form-item>
            <el-form-item label="最低置信度">
              <el-input-number v-model="form.min_signal_confidence" :min="0" :max="1" :step="0.05" />
            </el-form-item>
            <el-form-item label="ATR 止损止盈">
              <el-switch v-model="form.use_atr_sl_tp" />
            </el-form-item>
            <template v-if="form.use_atr_sl_tp">
              <el-form-item label="止损 ATR 倍">
                <el-input-number v-model="form.sl_atr" :min="0.5" :step="0.1" />
              </el-form-item>
              <el-form-item label="止盈 ATR 倍">
                <el-input-number v-model="form.tp_atr" :min="0.5" :step="0.1" />
              </el-form-item>
            </template>
            <template v-else>
              <el-form-item label="止损 %">
                <el-input-number v-model="form.sl_pct" :min="0.005" :step="0.005" :precision="3" />
              </el-form-item>
              <el-form-item label="止盈 %">
                <el-input-number v-model="form.tp_pct" :min="0.005" :step="0.005" :precision="3" />
              </el-form-item>
            </template>

            <el-divider content-position="left">纸面交易</el-divider>
            <el-form-item label="纸面模式"><el-switch v-model="form.paper_mode" /></el-form-item>
            <template v-if="form.paper_mode">
              <el-form-item label="初始资金">
                <el-input-number v-model="form.paper_initial_cash" :min="100" :step="1000" />
              </el-form-item>
              <el-form-item label="手续费率">
                <el-input-number v-model="form.fee_pct" :min="0" :step="0.0005" :precision="4" />
              </el-form-item>
              <el-form-item label="滑点率">
                <el-input-number v-model="form.slippage_pct" :min="0" :step="0.0005" :precision="4" />
              </el-form-item>
            </template>

            <el-form-item>
              <el-button type="primary" :loading="loading" @click="submit">运行一次</el-button>
              <el-button v-if="form.paper_mode" @click="loadPerformance">刷新绩效</el-button>
              <el-button v-if="form.paper_mode" type="danger" plain @click="resetPaper">
                重置纸面
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="15">
        <el-card v-if="result && (result as any).signal" shadow="never" class="panel-card">
          <SignalSummary :signal="(result as any).signal" />
          <div v-if="(result as any).signal?.gated" class="gate-note">
            <el-tag type="warning" size="small">已过滤为观望</el-tag>
            <span v-for="g in (result as any).signal?.gates ?? []" :key="g">{{ g }}</span>
          </div>
        </el-card>

        <el-card
          v-if="perf && perf.performance"
          shadow="never"
          class="panel-card"
          style="margin-bottom: 12px"
        >
          <template #header>
            <span>纸面绩效 · {{ perf.symbol }}</span>
          </template>
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="净值">
              {{ perf.performance.equity }} / {{ perf.performance.initial_cash }}
            </el-descriptions-item>
            <el-descriptions-item label="总收益">
              {{ pct(perf.performance.total_return) }}
            </el-descriptions-item>
            <el-descriptions-item label="最大回撤">
              {{ pct(perf.performance.max_drawdown) }}
            </el-descriptions-item>
            <el-descriptions-item label="已平仓笔数">
              {{ perf.performance.closed_trades }}
            </el-descriptions-item>
            <el-descriptions-item label="胜率">
              {{ pct(perf.performance.win_rate) }}
            </el-descriptions-item>
            <el-descriptions-item label="盈亏比">
              {{ perf.performance.profit_factor ?? "—" }}
            </el-descriptions-item>
            <el-descriptions-item label="已实现盈亏">
              {{ perf.performance.realized_pnl }}
            </el-descriptions-item>
            <el-descriptions-item label="浮动盈亏">
              {{ perf.performance.unrealized_pnl }}
            </el-descriptions-item>
            <el-descriptions-item label="累计手续费">
              {{ perf.performance.total_fees }}
            </el-descriptions-item>
          </el-descriptions>
          <EquityCurveChart
            v-if="equityChartData.length >= 2"
            :data="equityChartData"
            :capital-base="perf.performance.initial_cash"
          />
          <el-table
            v-if="perf.trades?.length"
            :data="perf.trades.slice().reverse()"
            size="small"
            max-height="240"
            style="margin-top: 10px"
          >
            <el-table-column prop="ts" label="时间" width="170" />
            <el-table-column prop="side" label="方向" width="70" />
            <el-table-column prop="price" label="价格" />
            <el-table-column prop="reason" label="原因" />
            <el-table-column prop="realized_pnl" label="实现盈亏" />
          </el-table>
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
            <el-table-column prop="kind" label="类型" width="70" />
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
.gate-note {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
