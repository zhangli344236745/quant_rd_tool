<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { stocksApi } from "@/api/stocks";
import { extractError } from "@/api/http";

const route = useRoute();
const router = useRouter();
const codeA = ref(String(route.query.a || ""));
const codeB = ref(String(route.query.b || ""));
const loading = ref(false);
const error = ref("");
const data = ref<{
  a: CompareSide;
  b: CompareSide;
} | null>(null);

interface CompareSide {
  code: string;
  qlib_code: string;
  stance?: string;
  summary?: string;
  report_mtime?: string;
  technical?: Record<string, unknown>;
  returns?: Record<string, unknown>;
  price?: Record<string, unknown>;
  risk?: Record<string, unknown>;
  ml?: Record<string, unknown> | null;
  macro_summary?: string;
}

async function compare() {
  const a = codeA.value.trim();
  const b = codeB.value.trim();
  if (!a || !b) {
    error.value = "请输入两只标的代码";
    return;
  }
  loading.value = true;
  error.value = "";
  data.value = null;
  try {
    const { data: res } = await stocksApi.reportsCompare(a, b);
    data.value = res;
    router.replace({ query: { a, b } });
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

function fmtPct(v: unknown) {
  if (typeof v !== "number") return "—";
  return `${(v * 100).toFixed(2)}%`;
}
</script>

<template>
  <div>
    <h1 class="page-title">报告对比</h1>
    <p class="page-desc">并排对比两只标的本地 report.json 中的立场、技术摘要与 ML 信号。</p>

    <el-card shadow="never" class="panel-card">
      <div class="toolbar">
        <el-input v-model="codeA" placeholder="代码 A，如 600519" style="max-width: 160px" />
        <span class="vs">vs</span>
        <el-input v-model="codeB" placeholder="代码 B，如 000001" style="max-width: 160px" />
        <el-button type="primary" :loading="loading" @click="compare">对比</el-button>
        <el-button @click="router.push({ name: 'astock-reports' })">报告库</el-button>
      </div>
      <el-alert v-if="error" type="error" :title="error" show-icon class="mt" />

      <el-row v-if="data" :gutter="16" class="mt">
        <el-col v-for="side in [data.a, data.b]" :key="side.code" :xs="24" :md="12">
          <el-card shadow="hover">
            <template #header>
              <div class="side-head">
                <span class="mono">{{ side.qlib_code }}</span>
                <el-tag v-if="side.stance" size="small">{{ side.stance }}</el-tag>
              </div>
            </template>
            <p v-if="side.summary" class="summary">{{ side.summary }}</p>
            <p v-if="side.macro_summary" class="macro-line"><strong>宏观：</strong>{{ side.macro_summary }}</p>
            <el-descriptions v-if="side.technical" :column="1" size="small" border class="mt-sm">
              <el-descriptions-item label="均线">{{ side.technical.ma_alignment ?? "—" }}</el-descriptions-item>
              <el-descriptions-item label="RSI">{{ side.technical.rsi_14 ?? "—" }}</el-descriptions-item>
              <el-descriptions-item label="RSI 区间">{{ side.technical.rsi_zone ?? "—" }}</el-descriptions-item>
            </el-descriptions>
            <el-descriptions v-if="side.returns" :column="2" size="small" class="mt-sm">
              <el-descriptions-item label="20日">{{ fmtPct(side.returns["20d"]) }}</el-descriptions-item>
              <el-descriptions-item label="60日">{{ fmtPct(side.returns["60d"]) }}</el-descriptions-item>
            </el-descriptions>
            <pre v-if="side.ml" class="ml-pre">{{ JSON.stringify(side.ml, null, 2) }}</pre>
            <p class="muted mono small">{{ side.report_mtime }}</p>
          </el-card>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.vs {
  color: var(--text-muted);
}
.mt {
  margin-top: 16px;
}
.mt-sm {
  margin-top: 12px;
}
.summary {
  margin: 0 0 8px;
  font-size: 14px;
  line-height: 1.5;
}
.macro-line {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--text-muted);
}
.ml-pre {
  margin-top: 12px;
  font-size: 11px;
  max-height: 160px;
  overflow: auto;
}
.side-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.small {
  font-size: 11px;
  margin-top: 8px;
}
</style>
