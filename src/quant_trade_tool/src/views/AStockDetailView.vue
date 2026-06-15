<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { jobsApi } from "@/api/jobs";
import { openJobDrawer } from "@/composables/jobDrawer";
import { stocksApi, type ProfileRow, type StockProfile } from "@/api/stocks";
import { extractError } from "@/api/http";

const route = useRoute();
const router = useRouter();
const code = computed(() => String(route.params.code || ""));

const loading = ref(false);
const tab = ref(String(route.query.tab || "profile"));
const reportLoading = ref(false);
const report = ref<{
  stance?: string;
  summary?: string;
  markdown?: string;
  report_mtime?: string;
  macro?: { summary?: string };
  technical?: Record<string, unknown>;
  compliance?: {
    run_id?: string;
    entry_hash?: string;
    content_hash?: string;
    integrity?: { valid?: boolean; locked?: boolean };
  };
} | null>(null);
const analyzeSubmitting = ref(false);
const profile = ref<StockProfile | null>(null);
const management = ref<Record<string, unknown>[]>([]);
const news = ref<Record<string, unknown>[]>([]);
const notices = ref<Record<string, unknown>[]>([]);
const noticeCategory = ref("全部");
const error = ref("");
const reportDiff = ref<{
  summary?: string;
  changes?: { field: string; from: unknown; to: unknown }[];
} | null>(null);
const versions = ref<
  { version_id: string; stance?: string; report_mtime?: string; locked?: boolean; content_hash?: string }[]
>([]);
const lockingVersion = ref<string | null>(null);

async function loadProfile() {
  const { data } = await stocksApi.profile(code.value);
  profile.value = data;
}

async function loadManagement() {
  const { data } = await stocksApi.management(code.value);
  management.value = data.items;
}

async function loadNews() {
  const { data } = await stocksApi.news(code.value, 30);
  news.value = data.items;
}

async function loadNotices() {
  const { data } = await stocksApi.notices(code.value, noticeCategory.value, 40);
  notices.value = data.items;
}

async function loadReport() {
  reportLoading.value = true;
  reportDiff.value = null;
  try {
    const { data } = await stocksApi.reportsLatest(code.value);
    report.value = data;
    try {
      const hist = await stocksApi.reportsHistory(code.value);
      versions.value = hist.data.items || [];
      if (hist.data.items.length > 1) {
        const { data: diff } = await stocksApi.reportsDiff(code.value);
        reportDiff.value = diff;
      }
    } catch {
      versions.value = [];
    }
  } catch {
    report.value = null;
  } finally {
    reportLoading.value = false;
  }
}

async function lockVersion(versionId: string) {
  if (versionId === "latest") return;
  lockingVersion.value = versionId;
  try {
    await stocksApi.reportsLock(code.value, versionId, { reason: "manual sign-off" });
    ElMessage.success(`已锁定版本 ${versionId}`);
    await loadReport();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    lockingVersion.value = null;
  }
}

async function submitQlib() {
  analyzeSubmitting.value = true;
  try {
    await jobsApi.qlibAnalyze({ code: code.value, years: 2, with_ml: true });
    ElMessage.success("已提交 Qlib 任务");
    openJobDrawer();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    analyzeSubmitting.value = false;
  }
}

async function submitFullAnalyze() {
  analyzeSubmitting.value = true;
  try {
    await jobsApi.analyzeStock({
      code: code.value,
      start_date: "2020-01-01",
      with_ml: true,
      with_openbb_enrichment: true,
    });
    ElMessage.success("已提交完整分析任务");
    openJobDrawer();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    analyzeSubmitting.value = false;
  }
}

async function loadTab(name: string) {
  if (name === "profile" && !profile.value) await loadProfile();
  if (name === "management" && management.value.length === 0) await loadManagement();
  if (name === "news" && news.value.length === 0) await loadNews();
  if (name === "notices") await loadNotices();
  if (name === "analysis") await loadReport();
}

async function refresh() {
  loading.value = true;
  error.value = "";
  profile.value = null;
  management.value = [];
  news.value = [];
  notices.value = [];
  try {
    await loadTab(tab.value);
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

watch(tab, async (name) => {
  loading.value = true;
  error.value = "";
  try {
    await loadTab(name);
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
});

watch(noticeCategory, () => {
  if (tab.value === "notices") loadNotices().catch((e) => (error.value = extractError(e)));
});

onMounted(refresh);

function rowsToTable(rows: ProfileRow[]) {
  return rows.map((r) => ({ field: r.key, value: r.value }));
}

const emTable = computed(() => rowsToTable(profile.value?.em || []));
const cninfoTable = computed(() => rowsToTable(profile.value?.cninfo || []));

function newsLink(row: Record<string, unknown>) {
  return String(row["新闻链接"] || row.url || "");
}
</script>

<template>
  <div>
    <div class="head-row">
      <el-button link @click="router.push({ name: 'astocks' })">← 返回列表</el-button>
      <div class="title-block">
        <h1 class="page-title">
          {{ profile?.name || code }}
          <span class="mono sub">{{ profile?.qlib_code || code }}</span>
        </h1>
      </div>
      <el-button type="primary" :loading="loading" @click="refresh">刷新</el-button>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-card shadow="never" class="panel-card">
      <el-tabs v-model="tab">
        <el-tab-pane label="基本信息" name="profile">
          <el-row v-loading="loading" :gutter="20">
            <el-col :span="12">
              <h3 class="sec">行情与指标（东财）</h3>
              <el-table :data="emTable" size="small" max-height="420">
                <el-table-column prop="field" label="项目" width="120" />
                <el-table-column prop="value" label="值" show-overflow-tooltip />
              </el-table>
            </el-col>
            <el-col :span="12">
              <h3 class="sec">公司概况（巨潮）</h3>
              <el-table :data="cninfoTable" size="small" max-height="420">
                <el-table-column prop="field" label="项目" width="120" />
                <el-table-column prop="value" label="值" show-overflow-tooltip />
              </el-table>
            </el-col>
          </el-row>
        </el-tab-pane>

        <el-tab-pane label="管理层变动" name="management">
          <el-table v-loading="loading" :data="management" size="small" stripe>
            <el-table-column
              v-for="col in management[0] ? Object.keys(management[0]) : []"
              :key="col"
              :prop="col"
              :label="col"
              min-width="120"
              show-overflow-tooltip
            />
          </el-table>
          <el-empty v-if="!loading && !management.length" description="暂无管理层变动记录" />
        </el-tab-pane>

        <el-tab-pane label="新闻资讯" name="news">
          <el-table v-loading="loading" :data="news" size="small">
            <el-table-column prop="发布时间" label="时间" width="160" />
            <el-table-column prop="新闻标题" label="标题" min-width="240">
              <template #default="{ row }">
                <a
                  v-if="newsLink(row)"
                  :href="newsLink(row)"
                  target="_blank"
                  rel="noopener"
                  class="news-link"
                >{{ row["新闻标题"] }}</a>
                <span v-else>{{ row["新闻标题"] }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="文章来源" label="来源" width="120" />
          </el-table>
          <el-empty v-if="!loading && !news.length" description="暂无新闻" />
        </el-tab-pane>

        <el-tab-pane label="分析" name="analysis">
          <div v-loading="reportLoading" class="analysis-pane">
            <div class="analysis-actions">
              <router-link
                :to="{ path: '/stock-var', query: { symbol: code, tab: 'symbol' } }"
                class="var-link"
              >
                <el-button>风险 VaR</el-button>
              </router-link>
              <el-button type="primary" :loading="analyzeSubmitting" @click="submitFullAnalyze">
                完整分析（OpenBB+ML）
              </el-button>
              <el-button type="warning" :loading="analyzeSubmitting" @click="submitQlib">
                Qlib 快分析
              </el-button>
              <el-button @click="loadReport">刷新报告</el-button>
            </div>
            <template v-if="report">
              <el-alert
                v-if="report.macro?.summary"
                type="info"
                :closable="false"
                class="macro-card"
                title="宏观环境（报告内 OpenBB）"
                :description="report.macro.summary"
              />
              <el-descriptions
                v-if="report.technical"
                :column="3"
                size="small"
                border
                class="tech-row"
              >
                <el-descriptions-item label="均线">{{ report.technical.ma_alignment ?? "—" }}</el-descriptions-item>
                <el-descriptions-item label="RSI">{{ report.technical.rsi_14 ?? "—" }}</el-descriptions-item>
                <el-descriptions-item label="区间">{{ report.technical.rsi_zone ?? "—" }}</el-descriptions-item>
              </el-descriptions>
              <div class="analysis-head">
                <el-tag v-if="report.stance" type="success" size="large">{{ report.stance }}</el-tag>
                <span v-if="report.report_mtime" class="mono muted">{{ report.report_mtime }}</span>
                <el-tag
                  v-if="report.compliance?.integrity?.valid === false"
                  type="danger"
                  size="small"
                >
                  完整性异常
                </el-tag>
                <el-tag
                  v-else-if="report.compliance?.run_id"
                  type="info"
                  size="small"
                >
                  审计 {{ report.compliance.run_id.slice(0, 8) }}
                </el-tag>
              </div>
              <p v-if="report.compliance?.entry_hash" class="muted small mono">
                链哈希 {{ report.compliance.entry_hash.slice(0, 16) }}…
              </p>
              <el-alert
                v-if="reportDiff?.summary"
                type="success"
                :closable="false"
                title="与上一版差异"
                :description="reportDiff.summary"
                class="diff-card"
              />
              <el-table
                v-if="reportDiff?.changes?.length"
                :data="reportDiff.changes"
                size="small"
                class="diff-table"
              >
                <el-table-column prop="field" label="字段" width="140" />
                <el-table-column prop="from" label="旧值" min-width="100" show-overflow-tooltip />
                <el-table-column prop="to" label="新值" min-width="100" show-overflow-tooltip />
              </el-table>
              <p v-if="versions.length" class="muted small">
                版本：
                <template v-for="(v, idx) in versions" :key="v.version_id">
                  <span>{{ v.version_id }}</span>
                  <el-tag v-if="v.locked" type="warning" size="small" class="ver-tag">已锁定</el-tag>
                  <el-button
                    v-else-if="v.version_id !== 'latest'"
                    link
                    type="primary"
                    size="small"
                    :loading="lockingVersion === v.version_id"
                    @click="lockVersion(v.version_id)"
                  >
                    锁定
                  </el-button>
                  <span v-if="idx < versions.length - 1">, </span>
                </template>
              </p>
              <p v-if="report.summary" class="analysis-summary">{{ report.summary }}</p>
              <el-scrollbar v-if="report.markdown" max-height="480" class="md-box">
                <pre class="md-pre">{{ report.markdown }}</pre>
              </el-scrollbar>
            </template>
            <el-empty v-else description="暂无本地报告，请先提交完整分析或 Qlib 任务" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="公司公告" name="notices">
          <div class="notice-bar">
            <el-select v-model="noticeCategory" style="width: 160px">
              <el-option label="全部" value="全部" />
              <el-option label="财务报告" value="财务报告" />
              <el-option label="重大事项" value="重大事项" />
            </el-select>
          </div>
          <el-table v-loading="loading" :data="notices" size="small" class="mt">
            <el-table-column prop="公告日期" label="日期" width="110" />
            <el-table-column prop="公告标题" label="标题" min-width="280" show-overflow-tooltip />
            <el-table-column prop="公告类型" label="类型" width="120" />
            <el-table-column label="链接" width="80">
              <template #default="{ row }">
                <a v-if="row['网址']" :href="String(row['网址'])" target="_blank" rel="noopener">打开</a>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loading && !notices.length" description="暂无公告" />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.head-row {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.title-block {
  flex: 1;
}

.sub {
  font-size: 0.9rem;
  color: var(--text-muted);
  margin-left: 10px;
  font-weight: 400;
}

.sec {
  margin: 0 0 12px;
  font-size: 0.95rem;
  color: var(--text-muted);
}

.mb {
  margin-bottom: 12px;
}

.mt {
  margin-top: 12px;
}

.notice-bar {
  margin-bottom: 8px;
}

.news-link {
  color: var(--accent);
  text-decoration: none;
}

.news-link:hover {
  text-decoration: underline;
}

.analysis-pane {
  min-height: 200px;
}

.analysis-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.diff-card {
  margin-bottom: 12px;
}
.diff-table {
  margin-bottom: 12px;
}
.macro-card {
  margin-bottom: 12px;
}

.tech-row {
  margin-bottom: 12px;
}

.analysis-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.ver-tag {
  margin-left: 4px;
}

.analysis-summary {
  line-height: 1.6;
  margin-bottom: 16px;
}

.md-box {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.2);
}

.md-pre {
  margin: 0;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
  font-family: var(--font-mono, monospace);
}
</style>
