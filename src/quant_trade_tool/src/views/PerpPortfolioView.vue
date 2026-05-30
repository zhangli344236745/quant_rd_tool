<script setup lang="ts">
import { reactive, ref } from "vue";
import { cryptoApi, type PerpPortfolioRequest } from "@/api/crypto";
import { extractError } from "@/api/http";
import ResultPanel from "@/components/ResultPanel.vue";

const form = reactive<PerpPortfolioRequest>({
  symbols: ["BTC", "ETH"],
  quote: "USDT",
  timeframe: "5m",
  ohlcv_limit: 800,
  leverage: 3,
  usdt_risk_fraction: 0.2,
  min_notional_usdt: 10,
  total_notional_usdt: 0,
  max_per_symbol_notional_usdt: 0,
  max_concurrent_positions: 0,
  dry_run: true,
  testnet: false,
  signal_only: false,
});

const symbolInput = ref("BTC,ETH");
const loading = ref(false);
const result = ref<unknown>(null);
const error = ref("");

function syncSymbols() {
  form.symbols = symbolInput.value
    .split(/[,，\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
}

async function submit() {
  syncSymbols();
  loading.value = true;
  error.value = "";
  result.value = null;
  try {
    const { data } = await cryptoApi.perpPortfolioRun({ ...form });
    result.value = data;
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

const rows = () => {
  const r = result.value as { results?: { symbol: string; result?: Record<string, unknown> }[] };
  return r?.results || [];
};
</script>

<template>
  <div>
    <h1 class="page-title">组合永续</h1>
    <p class="page-desc">/crypto/perp-portfolio/run — 多标的并行 run-once，可选组合预算约束。</p>

    <el-row :gutter="20">
      <el-col :span="9">
        <el-card shadow="never" class="panel-card">
          <el-form label-width="130px" size="small">
            <el-form-item label="标的列表">
              <el-input v-model="symbolInput" placeholder="BTC,ETH" @blur="syncSymbols" />
            </el-form-item>
            <el-form-item label="总预算 USDT">
              <el-input-number v-model="form.total_notional_usdt" :min="0" />
              <span class="hint">0 = 不限制</span>
            </el-form-item>
            <el-form-item label="单标的上限">
              <el-input-number v-model="form.max_per_symbol_notional_usdt" :min="0" />
            </el-form-item>
            <el-form-item label="最大持仓数">
              <el-input-number v-model="form.max_concurrent_positions" :min="0" />
            </el-form-item>
            <el-form-item label="杠杆"><el-input-number v-model="form.leverage" :min="1" /></el-form-item>
            <el-form-item label="Dry-run"><el-switch v-model="form.dry_run" /></el-form-item>
            <el-form-item label="仅信号"><el-switch v-model="form.signal_only" /></el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="loading" @click="submit">运行组合</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="15">
        <el-card v-if="rows().length" shadow="never" class="panel-card">
          <template #header>摘要</template>
          <el-table :data="rows()" size="small">
            <el-table-column prop="symbol" label="标的" width="80" />
            <el-table-column label="decision">
              <template #default="{ row }">
                {{ row.result?.decision || row.result?.perp_action || "—" }}
              </template>
            </el-table-column>
            <el-table-column label="message" show-overflow-tooltip>
              <template #default="{ row }">{{ row.result?.message }}</template>
            </el-table-column>
          </el-table>
        </el-card>
        <ResultPanel :loading="loading" :result="result" :error="error" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.hint {
  margin-left: 8px;
  font-size: 11px;
  color: var(--text-muted);
}
</style>
