<script setup lang="ts">
import { reactive, ref } from "vue";
import { cryptoApi, type SymbolVarReport } from "@/api/crypto";
import { jobsApi } from "@/api/jobs";
import { useJobSubmit } from "@/composables/useJobSubmit";
import ResultPanel from "@/components/ResultPanel.vue";
import SignalSummary from "@/components/SignalSummary.vue";

const symbolVar = ref<SymbolVarReport | null>(null);
const symbolVarError = ref("");

const form = reactive({
  symbol: "BTC",
  timeframe: "5m",
  limit: 800,
  data_dir: "data/crypto",
  with_ml: true,
  ml_algorithm: "both",
  with_options_vol: true,
});

const { submit, polling } = useJobSubmit();
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");

async function loadSymbolVarSummary(symbol: string) {
  symbolVar.value = null;
  symbolVarError.value = "";
  try {
    const { data } = await cryptoApi.varSymbol({
      symbol,
      notional_usdt: 10000,
      confidence: "0.99",
      horizon_days: 1,
      lookback_bars: 252,
      timeframe: "1d",
    });
    symbolVar.value = data;
  } catch (e) {
    symbolVarError.value = String(e);
  }
}

async function run(wait: boolean) {
  error.value = "";
  result.value = null;
  symbolVar.value = null;
  symbolVarError.value = "";
  try {
    await submit(() => jobsApi.cryptoAnalyze({ ...form }), {
      wait,
      onDone: async (r) => {
        result.value = {
          combined_signal: r.combined_signal,
          options_vol: r.options_vol,
          narrative: r.narrative,
          ...r,
        };
        await loadSymbolVarSummary(form.symbol);
      },
    });
  } catch (e) {
    error.value = String(e);
  }
}

const var99Usdt = () => symbolVar.value?.metrics?.["0.99"]?.var_usdt;

const combined = () =>
  (result.value?.combined_signal as Record<string, unknown>) || undefined;

const optionsVol = () =>
  (result.value?.options_vol as Record<string, unknown>) || undefined;

function optAlertType(level: string) {
  if (level === "hot") return "danger";
  if (level === "elevated") return "warning";
  return "info";
}
</script>

<template>
  <div>
    <h1 class="page-title">Crypto 行情分析</h1>
    <p class="page-desc">
      技术面 + ML + Binance 期权 IV 联合研判；默认后台任务，可在任务中心查看。
    </p>

    <el-row :gutter="20">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <el-form label-width="100px" @submit.prevent="run(true)">
            <el-form-item label="标的">
              <el-select v-model="form.symbol" style="width: 100%">
                <el-option label="BTC" value="BTC" />
                <el-option label="ETH" value="ETH" />
              </el-select>
            </el-form-item>
            <el-form-item label="周期">
              <el-select v-model="form.timeframe">
                <el-option label="5m" value="5m" />
                <el-option label="1d" value="1d" />
              </el-select>
            </el-form-item>
            <el-form-item label="K 线数量">
              <el-input-number v-model="form.limit" :min="100" :max="2000" />
            </el-form-item>
            <el-form-item label="ML">
              <el-switch v-model="form.with_ml" />
            </el-form-item>
            <el-form-item label="期权 IV">
              <el-switch v-model="form.with_options_vol" />
            </el-form-item>
            <el-form-item label="算法">
              <el-select v-model="form.ml_algorithm">
                <el-option label="both" value="both" />
                <el-option label="xgb" value="xgb" />
                <el-option label="lgb" value="lgb" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" native-type="submit" :loading="polling">分析并等待</el-button>
              <el-button :loading="polling" @click="run(false)">仅提交</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card v-if="combined()" shadow="never" class="panel-card">
          <template #header>综合信号</template>
          <SignalSummary :signal="combined()" />
        </el-card>
        <el-card v-if="symbolVar || symbolVarError" shadow="never" class="panel-card mt">
          <template #header>风险 VaR 摘要</template>
          <template v-if="symbolVar">
            <p class="cross-summary">
              1 日 99% VaR（名义 10,000 USDT）：
              <strong>{{ var99Usdt()?.toLocaleString(undefined, { maximumFractionDigits: 2 }) }} USDT</strong>
            </p>
            <router-link
              :to="{ path: '/crypto-var', query: { symbol: form.symbol, tab: 'symbol' } }"
              class="var-link"
            >
              查看完整 VaR →
            </router-link>
          </template>
          <p v-else class="muted small">{{ symbolVarError }}</p>
        </el-card>
        <el-card
          v-if="optionsVol()?.enabled"
          shadow="never"
          class="panel-card mt"
        >
          <template #header>期权波动 × 现货方向</template>
          <el-tag
            :type="optAlertType(String(optionsVol()?.alert_level || 'normal'))"
            size="small"
            class="mb"
          >
            {{ optionsVol()?.alert_level }}
          </el-tag>
          <p v-if="(optionsVol()?.cross_view as any)?.summary" class="cross-summary">
            {{ (optionsVol()?.cross_view as any).summary }}
          </p>
          <el-descriptions :column="2" size="small" border class="mt">
            <el-descriptions-item label="ATM IV">
              {{
                optionsVol()?.atm_iv != null
                  ? (Number(optionsVol()?.atm_iv) * 100).toFixed(1) + "%"
                  : "—"
              }}
            </el-descriptions-item>
            <el-descriptions-item label="IV 分位">
              {{ optionsVol()?.iv_percentile ?? "—" }}
            </el-descriptions-item>
            <el-descriptions-item label="24h Δ">
              {{
                optionsVol()?.iv_change_24h_pct != null
                  ? optionsVol()?.iv_change_24h_pct + "%"
                  : "—"
              }}
            </el-descriptions-item>
            <el-descriptions-item label="合约">
              {{ optionsVol()?.contract || "—" }}
            </el-descriptions-item>
            <el-descriptions-item
              v-if="optionsVol()?.peer_rank != null"
              label="横向排名"
            >
              #{{ optionsVol()?.peer_rank }}/{{ optionsVol()?.peer_count }}
            </el-descriptions-item>
            <el-descriptions-item
              v-if="optionsVol()?.hottest_peer"
              label="IV 最高"
            >
              {{ optionsVol()?.hottest_peer }}
            </el-descriptions-item>
          </el-descriptions>
          <p v-if="(optionsVol()?.advice as any)?.summary" class="muted small mt">
            {{ (optionsVol()?.advice as any).summary }}
          </p>
          <p
            v-if="((optionsVol()?.strike_ladder as any)?.purchase_summary)?.headline"
            class="purchase-headline small mt"
          >
            {{ ((optionsVol()?.strike_ladder as any).purchase_summary).headline }}
          </p>
        </el-card>
        <ResultPanel :loading="polling" :result="result" :error="error" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.mt {
  margin-top: 16px;
}
.mb {
  margin-bottom: 8px;
}
.cross-summary {
  font-size: 14px;
  line-height: 1.5;
  margin: 0;
}
.muted.small {
  font-size: 12px;
  color: var(--text-muted);
}
.var-link {
  display: inline-block;
  margin-top: 8px;
  font-size: 13px;
  color: var(--el-color-primary);
  text-decoration: none;
}
.var-link:hover {
  text-decoration: underline;
}
</style>
