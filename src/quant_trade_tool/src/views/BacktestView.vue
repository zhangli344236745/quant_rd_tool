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
        <el-card v-if="result?.oos_summary && form.signal_mode === 'ml'" shadow="never" class="panel-card mt">
          <template #header>OOS 协议摘要（ML Top-K）</template>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="覆盖标的">{{ result.oos_summary.instruments_with_oos ?? "—" }}</el-descriptions-item>
            <el-descriptions-item label="门控通过">{{ result.oos_summary.gate_pass_count ?? "—" }} / {{ result.oos_summary.instruments_with_oos ?? "—" }}</el-descriptions-item>
            <el-descriptions-item label="平均测试 IC">{{ result.oos_summary.mean_test_ic ?? "—" }}</el-descriptions-item>
            <el-descriptions-item label="通过率">{{ result.oos_summary.gate_pass_rate != null ? (result.oos_summary.gate_pass_rate * 100).toFixed(1) + '%' : "—" }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
        <el-card v-if="result?.execution_rules" shadow="never" class="panel-card mt">
          <template #header>A 股执行规则</template>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="T+1">{{ result.execution_rules.t_plus_one ? "是" : "否" }}</el-descriptions-item>
            <el-descriptions-item label="整手">{{ result.execution_rules.lot_size }} 股</el-descriptions-item>
            <el-descriptions-item label="涨跌停模型">{{ result.execution_rules.limit_model }}</el-descriptions-item>
            <el-descriptions-item label="印花税">{{ ((result.execution_rules.fee_schedule?.stamp_duty_rate ?? 0) * 100).toFixed(2) }}%（卖）</el-descriptions-item>
          </el-descriptions>
          <div v-if="result?.cost_summary" class="cost-tags mt">
            <el-tag type="info">佣金 {{ result.cost_summary.total_commission?.toFixed?.(2) ?? result.cost_summary.total_commission }}</el-tag>
            <el-tag type="warning">印花税 {{ result.cost_summary.total_stamp_duty?.toFixed?.(2) ?? result.cost_summary.total_stamp_duty }}</el-tag>
            <el-tag v-if="result.cost_summary.blocked_limit_up">涨停阻断 {{ result.cost_summary.blocked_limit_up }}</el-tag>
            <el-tag v-if="result.cost_summary.blocked_t_plus_one">T+1 阻断 {{ result.cost_summary.blocked_t_plus_one }}</el-tag>
          </div>
        </el-card>
        <el-card v-if="result?.audit_record" shadow="never" class="panel-card mt">
          <template #header>合规审计</template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="run_id">{{ result.audit_record.run_id }}</el-descriptions-item>
            <el-descriptions-item label="链哈希">{{ result.audit_record.entry_hash }}</el-descriptions-item>
            <el-descriptions-item label="内容哈希">{{ result.audit_record.content_hash }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
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
.cost-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
