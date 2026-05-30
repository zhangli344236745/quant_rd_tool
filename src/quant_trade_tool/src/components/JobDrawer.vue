<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { jobsApi, JOB_TYPE_LABELS, type JobRecord } from "@/api/jobs";
import { useActiveJobsPoll } from "@/composables/activeJobs";
import { jobDrawerVisible } from "@/composables/jobDrawer";
import { jobTypeLabel } from "@/composables/useJobSubmit";
import { extractError } from "@/api/http";

const router = useRouter();
const { items, activeCount, refresh: pollRefresh } = useActiveJobsPoll();
const loading = ref(false);
const error = ref("");

async function refresh() {
  loading.value = true;
  error.value = "";
  try {
    await pollRefresh();
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

function statusType(s: string) {
  if (s === "done") return "success";
  if (s === "failed") return "danger";
  if (s === "running") return "warning";
  if (s === "cancelled") return "info";
  return "";
}

function typeLabel(t: string) {
  return JOB_TYPE_LABELS[t] || jobTypeLabel(t);
}

async function cancelJob(row: JobRecord) {
  try {
    await jobsApi.cancel(row.id);
    await refresh();
  } catch (e) {
    error.value = extractError(e);
  }
}

async function retryJob(row: JobRecord) {
  try {
    await jobsApi.retry(row.id);
    await refresh();
  } catch (e) {
    error.value = extractError(e);
  }
}

function openResult(row: JobRecord) {
  jobDrawerVisible.value = false;
  if ((row.type === "qlib_analyze" || row.type === "analyze_stock") && row.code) {
    router.push({ name: "astock-detail", params: { code: row.code }, query: { tab: "analysis" } });
    return;
  }
  if (row.type === "backtest_run") {
    router.push({ name: "backtest" });
    return;
  }
  if (row.type === "macro_panel") {
    router.push({ name: "macro" });
    return;
  }
  if (row.type === "crypto_analyze") {
    router.push({ name: "analyze" });
    return;
  }
  router.push({ name: "tasks" });
}

watch(jobDrawerVisible, (v) => {
  if (v) refresh();
});

defineExpose({ activeCount, refresh });
</script>

<template>
  <el-drawer v-model="jobDrawerVisible" title="任务中心" size="520px" destroy-on-close>
    <div class="drawer-actions">
      <el-button size="small" :loading="loading" @click="refresh">刷新</el-button>
      <el-button size="small" link type="primary" @click="router.push({ name: 'tasks' })">完整页面 →</el-button>
    </div>
    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-table v-loading="loading" :data="items" size="small" class="mt" empty-text="暂无任务">
      <el-table-column label="类型" width="100">
        <template #default="{ row }">{{ typeLabel(row.type) }}</template>
      </el-table-column>
      <el-table-column prop="code" label="标的" width="100" show-overflow-tooltip />
      <el-table-column label="状态" width="88">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" width="64">
        <template #default="{ row }">{{ Math.round((row.progress || 0) * 100) }}%</template>
      </el-table-column>
      <el-table-column prop="message" label="说明" min-width="90" show-overflow-tooltip />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 'queued'" link type="warning" @click="cancelJob(row)">取消</el-button>
          <el-button v-if="row.status === 'failed'" link type="warning" @click="retryJob(row)">重试</el-button>
          <el-button v-if="row.status === 'done'" link type="primary" @click="openResult(row)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-drawer>
</template>

<style scoped>
.drawer-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}
.mb {
  margin-bottom: 12px;
}
.mt {
  margin-top: 12px;
}
</style>
