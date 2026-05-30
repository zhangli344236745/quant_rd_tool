<script setup lang="ts">
import { reactive, ref } from "vue";
import { cryptoApi, type PerpBotRequest } from "@/api/crypto";
import { extractError } from "@/api/http";
import ResultPanel from "@/components/ResultPanel.vue";
import SignalSummary from "@/components/SignalSummary.vue";

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
</script>

<template>
  <div>
    <h1 class="page-title">永续 Bot</h1>
    <p class="page-desc">/crypto/perp-bot/run — ATR 定仓、熔断、原生/软保护、JSONL 遥测。</p>

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
