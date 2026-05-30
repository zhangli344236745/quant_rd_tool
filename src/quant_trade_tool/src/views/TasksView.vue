<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { jobsApi, JOB_TYPE_LABELS, type JobRecord } from "@/api/jobs";
import { jobTypeLabel } from "@/composables/useJobSubmit";
import { useJobEvents } from "@/composables/useJobEvents";
import { extractError } from "@/api/http";

const router = useRouter();
const items = ref<JobRecord[]>([]);
const filterStatus = ref("");
const loading = ref(false);
const error = ref("");
const selected = ref<JobRecord | null>(null);
const result = ref<Record<string, unknown> | null>(null);
const resultLoading = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;

const selectedId = computed(() => selected.value?.id);
const { logs, terminal, connect, disconnect } = useJobEvents(() => selectedId.value);

const selectedLive = computed(
  () =>
    selected.value &&
    (selected.value.status === "running" || selected.value.status === "queued"),
);

async function refresh() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await jobsApi.list({
      status: filterStatus.value || undefined,
      limit: 100,
    });
    items.value = data.items;
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

async function retryJob(row: JobRecord) {
  try {
    await jobsApi.retry(row.id);
    await refresh();
    const updated = items.value.find((j) => j.id === row.id);
    if (updated) selected.value = updated;
  } catch (e) {
    error.value = extractError(e);
  }
}

async function loadResult(row: JobRecord) {
  selected.value = row;
  if (row.status !== "done") {
    result.value = null;
    return;
  }
  resultLoading.value = true;
  try {
    const { data } = await jobsApi.result(row.id);
    result.value = data;
  } catch (e) {
    result.value = { error: extractError(e) };
  } finally {
    resultLoading.value = false;
  }
}

function navigate(row: JobRecord) {
  if (row.type === "crypto_analyze" && row.code) {
    router.push({ name: "analyze" });
    return;
  }
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
  }
}

watch(
  [selectedId, selectedLive],
  ([id, live]) => {
    disconnect();
    if (id && live) connect();
  },
  { immediate: true },
);

watch(terminal, (t) => {
  if (t) refresh();
});

onMounted(() => {
  refresh();
  timer = setInterval(refresh, 4000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
  disconnect();
});
</script>

<template>
  <div>
    <h1 class="page-title">任务中心</h1>
    <p class="page-desc">统一查看 A 股分析、回测、宏观、Crypto 等后台任务。</p>

    <div class="toolbar">
      <el-select v-model="filterStatus" clearable placeholder="状态" style="width: 120px" @change="refresh">
        <el-option label="queued" value="queued" />
        <el-option label="running" value="running" />
        <el-option label="done" value="done" />
        <el-option label="failed" value="failed" />
      </el-select>
      <el-button type="primary" :loading="loading" @click="refresh">刷新</el-button>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-row :gutter="16">
      <el-col :span="14">
        <el-table
          v-loading="loading"
          :data="items"
          size="small"
          highlight-current-row
          @row-click="loadResult"
        >
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              {{ JOB_TYPE_LABELS[row.type] || jobTypeLabel(row.type) }}
            </template>
          </el-table-column>
          <el-table-column prop="code" label="标的" width="120" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="error" label="错误" width="120" show-overflow-tooltip />
          <el-table-column label="进度" width="70">
            <template #default="{ row }">{{ Math.round((row.progress || 0) * 100) }}%</template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="100" show-overflow-tooltip />
          <el-table-column prop="created_at" label="创建" width="170" show-overflow-tooltip />
          <el-table-column label="" width="120">
            <template #default="{ row }">
              <el-button v-if="row.status === 'failed'" link type="warning" @click.stop="retryJob(row)">
                重试
              </el-button>
              <el-button v-if="row.status === 'done'" link type="primary" @click.stop="navigate(row)">
                跳转
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never" class="panel-card" v-loading="resultLoading">
          <template #header>任务结果</template>
          <el-empty v-if="!selected" description="选择左侧任务" />
          <template v-else>
            <p class="mono small">{{ selected.id }}</p>
            <div v-if="selectedLive || logs.length" class="log-panel mb">
              <div class="log-head">实时日志 (SSE)</div>
              <el-scrollbar max-height="220">
                <div v-for="(line, i) in logs" :key="i" class="log-line">
                  <span v-if="line.created_at" class="log-ts">{{ line.created_at }}</span>
                  <span v-if="line.level" class="log-lv">{{ line.level }}</span>
                  {{ line.message || JSON.stringify(line) }}
                  <span v-if="line.progress != null" class="log-pct">
                    {{ Math.round((line.progress || 0) * 100) }}%
                  </span>
                </div>
                <p v-if="!logs.length && selectedLive" class="log-empty">等待事件…</p>
              </el-scrollbar>
            </div>
            <el-scrollbar v-if="result?.markdown" max-height="400" class="mb">
              <pre class="md-pre">{{ result.markdown }}</pre>
            </el-scrollbar>
            <pre v-if="result" class="json-viewer">{{ JSON.stringify(result, null, 2) }}</pre>
            <el-empty v-else-if="selected.status !== 'done'" :description="`状态: ${selected.status}`" />
          </template>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.mb {
  margin-bottom: 12px;
}
.small {
  font-size: 11px;
  color: var(--text-muted);
}
.mb {
  margin-bottom: 12px;
}
.md-pre {
  margin: 0;
  padding: 8px;
  white-space: pre-wrap;
  font-size: 12px;
}
.log-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px;
}
.log-head {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.log-line {
  font-size: 11px;
  font-family: var(--font-mono, monospace);
  margin-bottom: 4px;
  word-break: break-all;
}
.log-ts,
.log-lv {
  margin-right: 6px;
  color: var(--text-muted);
}
.log-pct {
  margin-left: 6px;
  color: var(--el-color-primary);
}
.log-empty {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0;
}
</style>
