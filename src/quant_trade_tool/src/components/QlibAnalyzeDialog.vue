<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { jobsApi } from "@/api/jobs";
import { openJobDrawer } from "@/composables/jobDrawer";
import { extractError } from "@/api/http";

const props = defineProps<{
  modelValue: boolean;
  code: string;
  name?: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [boolean];
}>();

const loading = ref(false);
const error = ref("");

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});

async function run() {
  if (!props.code) return;
  loading.value = true;
  error.value = "";
  try {
    const { data } = await jobsApi.qlibAnalyze({
      code: props.code,
      years: 2,
      refresh: true,
      with_ml: true,
      ml_algorithm: "both",
    });
    ElMessage.success(`已提交分析任务：${data.job_id.slice(0, 8)}…`);
    openJobDrawer();
    visible.value = false;
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="`Qlib 分析 — ${name || code} (${code})`"
    width="520px"
    destroy-on-close
  >
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="提交后台任务：拉取近 2 年日线 → qlib → 技术面 + ML。完成后在「任务」抽屉或详情「分析」页查看报告。"
      class="mb"
    />
    <el-alert v-if="error" type="error" :title="error" show-icon />

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="run">提交分析</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mb {
  margin-bottom: 12px;
}
</style>
