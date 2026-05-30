<script setup lang="ts">
import { reactive, ref } from "vue";
import { cryptoApi } from "@/api/crypto";
import { extractError } from "@/api/http";
import ResultPanel from "@/components/ResultPanel.vue";
import SignalSummary from "@/components/SignalSummary.vue";

const form = reactive({
  symbol: "BTC",
  quote: "USDT",
  quote_amount: 50,
  timeframe: "1d",
  dry_run: true,
  testnet: false,
  signal_only: false,
});

const loading = ref(false);
const result = ref<unknown>(null);
const error = ref("");

async function submit() {
  loading.value = true;
  error.value = "";
  result.value = null;
  try {
    const { data } = await cryptoApi.spotBotRun({ ...form });
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
    <h1 class="page-title">现货 Bot</h1>
    <p class="page-desc">/crypto/bot/run — 币安现货，默认 dry-run。</p>

    <el-row :gutter="20">
      <el-col :span="9">
        <el-card shadow="never" class="panel-card">
          <el-form label-width="110px">
            <el-form-item label="标的"><el-input v-model="form.symbol" /></el-form-item>
            <el-form-item label="计价"><el-input v-model="form.quote" /></el-form-item>
            <el-form-item label="金额 USDT"><el-input-number v-model="form.quote_amount" :min="5" /></el-form-item>
            <el-form-item label="周期"><el-input v-model="form.timeframe" /></el-form-item>
            <el-form-item label="Dry-run"><el-switch v-model="form.dry_run" /></el-form-item>
            <el-form-item label="测试网"><el-switch v-model="form.testnet" /></el-form-item>
            <el-form-item label="仅信号"><el-switch v-model="form.signal_only" /></el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="loading" @click="submit">运行</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="15">
        <el-card v-if="result && (result as any).signal" shadow="never" class="panel-card">
          <SignalSummary :signal="(result as any).signal" />
        </el-card>
        <ResultPanel :loading="loading" :result="result" :error="error" />
      </el-col>
    </el-row>
  </div>
</template>
