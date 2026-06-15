<script setup lang="ts">
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { jobsApi } from "@/api/jobs";
import { stocksApi } from "@/api/stocks";
import { openJobDrawer } from "@/composables/jobDrawer";
import { extractError } from "@/api/http";

const q = ref("");
const hasReport = ref<boolean | undefined>(undefined);
const stanceIn = ref<string[]>([]);
const watchlistOnly = ref(false);
const highImpactOnly = ref(false);
const noticeKeyword = ref("");
const jobType = ref<"qlib_analyze" | "analyze_stock" | "stock_workflow">("qlib_analyze");
const limit = ref(20);
const loading = ref(false);
const enqueueing = ref(false);
const items = ref<Record<string, unknown>[]>([]);
const total = ref(0);
const selected = ref<Record<string, unknown>[]>([]);

async function search() {
  loading.value = true;
  try {
    const { data } = await stocksApi.screener({
      q: q.value.trim(),
      has_report: hasReport.value ?? null,
      stance_in: stanceIn.value,
      watchlist_only: watchlistOnly.value,
      high_impact_only: highImpactOnly.value,
      notice_keyword: noticeKeyword.value.trim(),
      page: 1,
      page_size: 100,
    });
    items.value = data.items;
    total.value = data.total;
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

async function enqueueSelected() {
  const codes = selected.value.map((r) => String(r.code));
  if (!codes.length) {
    ElMessage.warning("请先勾选标的");
    return;
  }
  enqueueing.value = true;
  try {
    const { data } = await jobsApi.screenerEnqueue({
      codes,
      job_type: jobType.value,
      limit: codes.length,
      max_attempts: 2,
    });
    ElMessage.success(`已入队 ${data.enqueued} 个任务`);
    openJobDrawer();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    enqueueing.value = false;
  }
}

async function enqueueFiltered() {
  enqueueing.value = true;
  try {
    const { data } = await jobsApi.screenerEnqueue({
      q: q.value.trim(),
      has_report: hasReport.value ?? null,
      stance_in: stanceIn.value,
      watchlist_only: watchlistOnly.value,
      high_impact_only: highImpactOnly.value,
      notice_keyword: noticeKeyword.value.trim(),
      limit: limit.value,
      job_type: jobType.value,
      max_attempts: 2,
    });
    ElMessage.success(`匹配 ${data.matched}，入队 ${data.enqueued}`);
    openJobDrawer();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    enqueueing.value = false;
  }
}
</script>

<template>
  <div>
    <h1 class="page-title">选股器</h1>
    <p class="page-desc">按条件筛选 A 股并批量提交后台分析任务；支持高影响公告与关键词过滤。</p>

    <el-card shadow="never" class="panel-card">
      <el-form :inline="true" size="small">
        <el-form-item label="搜索">
          <el-input v-model="q" placeholder="代码/名称" clearable @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="报告">
          <el-select v-model="hasReport" placeholder="全部" clearable style="width: 110px">
            <el-option label="有报告" :value="true" />
            <el-option label="无报告" :value="false" />
          </el-select>
        </el-form-item>
        <el-form-item label="立场">
          <el-select v-model="stanceIn" multiple collapse-tags placeholder="任意" style="width: 160px">
            <el-option label="看涨" value="看涨" />
            <el-option label="看跌" value="看跌" />
            <el-option label="谨慎" value="谨慎" />
            <el-option label="中性" value="中性" />
          </el-select>
        </el-form-item>
        <el-form-item label="仅自选">
          <el-switch v-model="watchlistOnly" />
        </el-form-item>
        <el-form-item label="高影响公告">
          <el-switch v-model="highImpactOnly" />
        </el-form-item>
        <el-form-item label="公告关键词">
          <el-input v-model="noticeKeyword" placeholder="如 减持" clearable style="width: 120px" />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="jobType" style="width: 150px">
            <el-option label="Qlib 快分析" value="qlib_analyze" />
            <el-option label="完整分析" value="analyze_stock" />
            <el-option label="Workflow 分析" value="stock_workflow" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="search">筛选</el-button>
        </el-form-item>
      </el-form>

      <div class="toolbar">
        <span class="muted">共 {{ total }} 条，已选 {{ selected.length }}</span>
        <el-button :loading="enqueueing" :disabled="!selected.length" @click="enqueueSelected">
          勾选入队
        </el-button>
        <el-button type="warning" :loading="enqueueing" @click="enqueueFiltered">
          按条件入队（最多 {{ limit }}）
        </el-button>
        <el-input-number v-model="limit" :min="1" :max="50" size="small" />
      </div>

      <el-table
        v-loading="loading"
        :data="items"
        size="small"
        stripe
        @selection-change="(rows) => (selected = rows)"
      >
        <el-table-column type="selection" width="40" />
        <el-table-column prop="code" label="代码" width="90" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="stance" label="立场" width="80" />
        <el-table-column prop="has_report" label="报告" width="70">
          <template #default="{ row }">{{ row.has_report ? "有" : "—" }}</template>
        </el-table-column>
        <el-table-column prop="high_impact" label="高影响" width="72">
          <template #default="{ row }">{{ row.high_impact ? "是" : "—" }}</template>
        </el-table-column>
        <el-table-column prop="report_mtime" label="报告时间" width="180" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin: 12px 0;
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
