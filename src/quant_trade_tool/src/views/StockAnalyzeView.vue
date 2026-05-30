<script setup lang="ts">
import { reactive, ref } from "vue";
import { jobsApi } from "@/api/jobs";
import { useJobSubmit } from "@/composables/useJobSubmit";
import ResultPanel from "@/components/ResultPanel.vue";

const form = reactive({
  code: "600519",
  start_date: "2020-01-01",
  data_dir: "data/stocks",
  refresh: false,
  data_provider: "auto",
  with_ml: true,
  ml_algorithm: "both",
  with_openbb_enrichment: true,
});

const { submit, polling } = useJobSubmit();
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");

async function run(wait: boolean) {
  error.value = "";
  result.value = null;
  try {
    await submit(() => jobsApi.analyzeStock({ ...form }), {
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
    <h1 class="page-title">A 股个股分析</h1>
    <p class="page-desc">完整 analyze 管线（行情 + qlib + OpenBB），默认提交后台任务。</p>

    <el-row :gutter="20">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <el-form label-width="120px" size="small">
            <el-form-item label="代码">
              <el-input v-model="form.code" placeholder="600519" />
            </el-form-item>
            <el-form-item label="起始日期">
              <el-input v-model="form.start_date" />
            </el-form-item>
            <el-form-item label="行情源">
              <el-select v-model="form.data_provider">
                <el-option label="auto" value="auto" />
                <el-option label="akshare" value="akshare" />
                <el-option label="openbb" value="openbb" />
              </el-select>
            </el-form-item>
            <el-form-item label="强制刷新">
              <el-switch v-model="form.refresh" />
            </el-form-item>
            <el-form-item label="ML">
              <el-switch v-model="form.with_ml" />
            </el-form-item>
            <el-form-item label="OpenBB 增强">
              <el-switch v-model="form.with_openbb_enrichment" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="polling" @click="run(true)">提交并等待</el-button>
              <el-button :loading="polling" @click="run(false)">仅提交</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="14">
        <ResultPanel :loading="polling" :result="result" :error="error" title="分析摘要" />
      </el-col>
    </el-row>
  </div>
</template>
