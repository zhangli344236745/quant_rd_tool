<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { stocksApi } from "@/api/stocks";
import { getApiBase } from "@/config";
import { extractError } from "@/api/http";

const router = useRouter();
const q = ref("");
const page = ref(1);
const pageSize = ref(50);
const total = ref(0);
const items = ref<
  { code: string; qlib_code: string; stance?: string; summary?: string; report_mtime?: string }[]
>([]);
const loading = ref(false);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await stocksApi.reportsList({
      q: q.value.trim(),
      page: page.value,
      page_size: pageSize.value,
    });
    items.value = data.items;
    total.value = data.total;
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

function openDetail(code: string) {
  router.push({ name: "astock-detail", params: { code }, query: { tab: "analysis" } });
}

function exportZip() {
  const base = getApiBase();
  const prefix = base ? base.replace(/\/$/, "") : `${window.location.origin}/api/v1`;
  const url = `${prefix}/stocks/reports/export`;
  window.open(url, "_blank");
  ElMessage.success("正在下载报告 ZIP");
}

let debounce: ReturnType<typeof setTimeout> | undefined;
watch(q, () => {
  page.value = 1;
  clearTimeout(debounce);
  debounce = setTimeout(load, 400);
});

onMounted(load);
</script>

<template>
  <div>
    <h1 class="page-title">报告库</h1>
    <p class="page-desc">本地已生成 report.json 的 A 股标的，按更新时间排序。</p>

    <el-card shadow="never" class="panel-card">
      <div class="toolbar">
        <el-input v-model="q" placeholder="代码 / qlib" clearable style="max-width: 280px" @keyup.enter="load" />
        <el-button type="primary" :loading="loading" @click="load">刷新</el-button>
        <el-button @click="router.push({ name: 'astock-compare' })">两只对比</el-button>
        <el-button @click="exportZip">导出 ZIP</el-button>
        <span class="total mono">共 {{ total }} 份</span>
      </div>

      <el-alert v-if="error" type="error" :title="error" show-icon class="mt" />

      <el-table v-loading="loading" :data="items" stripe class="mt" @row-click="(r) => openDetail(r.code)">
        <el-table-column prop="code" label="代码" width="100" />
        <el-table-column prop="qlib_code" label="Qlib" width="110" />
        <el-table-column prop="stance" label="立场" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.stance" size="small">{{ row.stance }}</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip />
        <el-table-column prop="report_mtime" label="更新时间" width="200" />
        <el-table-column label="" width="80" align="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row.code)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          background
          @current-change="load"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
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
</style>
