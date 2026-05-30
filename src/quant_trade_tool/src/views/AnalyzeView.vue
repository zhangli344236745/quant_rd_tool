<script setup lang="ts">
import { reactive, ref } from "vue";
import { jobsApi } from "@/api/jobs";
import { useJobSubmit } from "@/composables/useJobSubmit";
import ResultPanel from "@/components/ResultPanel.vue";
import SignalSummary from "@/components/SignalSummary.vue";

const form = reactive({
  symbol: "BTC",
  timeframe: "5m",
  limit: 800,
  data_dir: "data/crypto",
  with_ml: true,
  ml_algorithm: "both",
});

const { submit, polling } = useJobSubmit();
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");

async function run(wait: boolean) {
  error.value = "";
  result.value = null;
  try {
    await submit(() => jobsApi.cryptoAnalyze({ ...form }), {
      wait,
      onDone: (r) => {
        result.value = { combined_signal: r.combined_signal, ...r };
      },
    });
  } catch (e) {
    error.value = String(e);
  }
}

const combined = () =>
  (result.value?.combined_signal as Record<string, unknown>) || undefined;
</script>

<template>
  <div>
    <h1 class="page-title">Crypto 行情分析</h1>
    <p class="page-desc">技术面 + ML 综合信号；默认后台任务，可在任务中心查看。</p>

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
        <ResultPanel :loading="polling" :result="result" :error="error" />
      </el-col>
    </el-row>
  </div>
</template>
