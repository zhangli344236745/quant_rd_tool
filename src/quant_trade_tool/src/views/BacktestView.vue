<script setup lang="ts">
import { reactive, ref } from "vue";
import { jobsApi } from "@/api/jobs";
import { useJobSubmit } from "@/composables/useJobSubmit";
import ResultPanel from "@/components/ResultPanel.vue";

const symbolsText = ref("600519,000858,601318");
const form = reactive({
  start_date: "2023-01-01",
  lookback: 20,
  topk: 3,
  signal_mode: "momentum",
  ml_algorithm: "lgb",
  data_provider: "auto",
});

const { submit, polling } = useJobSubmit();
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");

function parseSymbols() {
  return symbolsText.value
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

async function run(wait: boolean) {
  error.value = "";
  result.value = null;
  const symbols = parseSymbols();
  if (!symbols.length) {
    error.value = "请填写至少一只股票代码";
    return;
  }
  try {
    await submit(() => jobsApi.backtest({ ...form, symbols }), {
      wait,
      onDone: (r) => {
        result.value = r;
      },
    });
  } catch (e) {
    error.value = String(e);
  }
}
</script>

<template>
  <div>
    <h1 class="page-title">组合回测</h1>
    <p class="page-desc">qlib 动量 / ML Top-K 轮动回测，结果在任务中心查看。</p>

    <el-row :gutter="20">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <el-form label-width="100px" size="small">
            <el-form-item label="股票列表">
              <el-input v-model="symbolsText" type="textarea" :rows="2" placeholder="逗号分隔" />
            </el-form-item>
            <el-form-item label="区间起">
              <el-input v-model="form.start_date" />
            </el-form-item>
            <el-form-item label="动量窗口">
              <el-input-number v-model="form.lookback" :min="5" :max="120" />
            </el-form-item>
            <el-form-item label="Top-K">
              <el-input-number v-model="form.topk" :min="1" :max="20" />
            </el-form-item>
            <el-form-item label="信号">
              <el-select v-model="form.signal_mode">
                <el-option label="动量" value="momentum" />
                <el-option label="ML" value="ml" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="polling" @click="run(true)">提交并等待</el-button>
              <el-button @click="run(false)">仅提交</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="14">
        <ResultPanel :loading="polling" :result="result" :error="error" title="回测摘要" />
        <el-card v-if="result?.advice" shadow="never" class="panel-card mt">
          <template #header>投资建议</template>
          <pre class="advice">{{ JSON.stringify(result.advice, null, 2) }}</pre>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.mt {
  margin-top: 16px;
}
.advice {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
