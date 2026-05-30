<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import QlibAnalyzeDialog from "@/components/QlibAnalyzeDialog.vue";
import { jobsApi } from "@/api/jobs";
import { openJobDrawer } from "@/composables/jobDrawer";
import { stocksApi, type StockListItem } from "@/api/stocks";
import { extractError } from "@/api/http";

const router = useRouter();
const listMode = ref<"all" | "watch" | "reports">("all");
const watchCodes = ref<Set<string>>(new Set());
const reportCodes = ref<Set<string>>(new Set());
const qlibDialogVisible = ref(false);
const qlibTarget = ref<StockListItem | null>(null);
const selected = ref<StockListItem[]>([]);
const q = ref("");
const page = ref(1);
const pageSize = ref(50);
const total = ref(0);
const items = ref<StockListItem[]>([]);
const loading = ref(false);
const error = ref("");

async function loadWatchlist() {
  try {
    const { data } = await stocksApi.watchlist();
    watchCodes.value = new Set(data.items.map((i) => i.code));
  } catch {
    watchCodes.value = new Set();
  }
}

async function loadReportCodes() {
  try {
    const { data } = await stocksApi.reportsList({ page: 1, page_size: 500 });
    reportCodes.value = new Set(data.items.map((i) => i.code));
  } catch {
    reportCodes.value = new Set();
  }
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await stocksApi.list({
      q: q.value.trim(),
      page: page.value,
      page_size: pageSize.value,
    });
    let rows = data.items;
    if (listMode.value === "watch") {
      rows = rows.filter((r) => watchCodes.value.has(r.code));
    } else if (listMode.value === "reports") {
      rows = rows.filter((r) => reportCodes.value.has(r.code));
    }
    items.value = rows;
    total.value = listMode.value === "all" ? data.total : rows.length;
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

async function toggleWatch(row: StockListItem, e?: Event) {
  e?.stopPropagation();
  try {
    if (watchCodes.value.has(row.code)) {
      await stocksApi.removeWatchlist(row.code);
      watchCodes.value.delete(row.code);
    } else {
      await stocksApi.addWatchlist(row.code, row.name);
      watchCodes.value.add(row.code);
    }
    if (listMode.value === "watch") await load();
  } catch (err) {
    ElMessage.error(extractError(err));
  }
}

function openDetail(row: StockListItem) {
  router.push({ name: "astock-detail", params: { code: row.code } });
}

function openQlibAnalyze(row: StockListItem, e?: Event) {
  e?.stopPropagation();
  qlibTarget.value = row;
  qlibDialogVisible.value = true;
}

async function batchQlib() {
  if (!selected.value.length) {
    ElMessage.warning("请先勾选股票");
    return;
  }
  try {
    const { data } = await jobsApi.batchQlib({
      codes: selected.value.map((r) => r.code),
      years: 2,
      refresh: true,
      with_ml: true,
    });
    ElMessage.success(`已提交 ${data.job_ids.length} 个任务`);
    openJobDrawer();
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

let debounceTimer: ReturnType<typeof setTimeout> | undefined;
watch(q, () => {
  page.value = 1;
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(load, 400);
});

watch(listMode, async (mode) => {
  page.value = 1;
  if (mode === "reports" && reportCodes.value.size === 0) await loadReportCodes();
  load();
});

onMounted(async () => {
  await loadWatchlist();
  await loadReportCodes();
  await load();
});
</script>

<template>
  <div>
    <h1 class="page-title">A 股公司</h1>
    <p class="page-desc">全市场列表、自选、后台 Qlib 分析任务与报告回看。</p>

    <el-card shadow="never" class="panel-card">
      <div class="toolbar">
        <el-radio-group v-model="listMode" size="small">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="watch">自选</el-radio-button>
          <el-radio-button value="reports">有报告</el-radio-button>
        </el-radio-group>
        <el-button link type="primary" @click="router.push({ name: 'astock-reports' })">报告库 →</el-button>
        <el-input
          v-model="q"
          placeholder="搜索代码或名称"
          clearable
          style="max-width: 320px"
          @keyup.enter="load"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" :loading="loading" @click="load">刷新</el-button>
        <el-button type="warning" :disabled="!selected.length" @click="batchQlib">
          批量 Qlib（{{ selected.length }}）
        </el-button>
        <span class="total mono">共 {{ total }} 家</span>
      </div>

      <el-alert v-if="error" type="error" :title="error" show-icon class="mt" />

      <el-table
        v-loading="loading"
        :data="items"
        stripe
        class="mt"
        highlight-current-row
        @row-click="openDetail"
        @selection-change="(rows: StockListItem[]) => (selected = rows)"
      >
        <el-table-column type="selection" width="42" />
        <el-table-column label="" width="44">
          <template #default="{ row }">
            <el-button
              link
              :type="watchCodes.has(row.code) ? 'warning' : 'info'"
              @click="(e) => toggleWatch(row, e)"
            >
              {{ watchCodes.has(row.code) ? "★" : "☆" }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="代码" width="100">
          <template #default="{ row }">
            <span class="mono linkish">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="qlib_code" label="Qlib" width="110">
          <template #default="{ row }">
            <span class="mono muted">{{ row.qlib_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="操作" width="180" align="right" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">详情</el-button>
            <el-button link type="warning" @click="(e) => openQlibAnalyze(row, e)">Qlib</el-button>
          </template>
        </el-table-column>
      </el-table>

      <QlibAnalyzeDialog
        v-model="qlibDialogVisible"
        :code="qlibTarget?.code || ''"
        :name="qlibTarget?.name"
      />

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="load"
          @size-change="
            () => {
              page = 1;
              load();
            }
          "
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.total {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 13px;
}

.mt {
  margin-top: 16px;
}

.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.linkish {
  color: var(--accent);
  cursor: pointer;
}

.muted {
  color: var(--text-muted);
}
</style>
