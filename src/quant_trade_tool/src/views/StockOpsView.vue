<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { stocksApi, type StockOpsSummary } from "@/api/stocks";
import { extractError } from "@/api/http";
import { formatBeijing } from "@/utils/datetime";

function formatTimeCol(_r: unknown, _c: unknown, v: string) {
  return formatBeijing(v);
}
import AlertFeedPanel from "@/components/AlertFeedPanel.vue";
import { useNotify } from "@/composables/useNotify";

const router = useRouter();
const notify = useNotify();
const dataDir = "data/stocks";

const loading = ref(false);
const error = ref("");
const summary = ref<StockOpsSummary | null>(null);
const autoRefresh = ref(true);
let timer: ReturnType<typeof setInterval> | undefined;

const freshnessItems = computed(() => summary.value?.data_freshness?.items || []);
const topAnnouncements = computed(() => summary.value?.announcements?.top_items || []);

function statusTagType(status: string) {
  if (status === "running") return "success";
  if (status === "error") return "danger";
  return "info";
}

async function loadSummary() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await stocksApi.opsSummary({ data_dir: dataDir });
    summary.value = data;
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

async function probeConnectivity() {
  try {
    const { data } = await stocksApi.opsConnectivity({ data_dir: dataDir });
    notify.info(
      data.ok ? "AkShare 连通正常" : "AkShare 连通失败",
      data.ok ? `${data.source} · ${data.latency_ms}ms` : data.error,
    );
    await loadSummary();
  } catch (e) {
    notify.error("探测失败", extractError(e));
  }
}

onMounted(async () => {
  await loadSummary();
  timer = setInterval(() => {
    if (autoRefresh.value) loadSummary();
  }, 15000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div>
    <h1 class="page-title">A股 运营看板</h1>
    <p class="page-desc">数据新鲜度、AkShare 连通性、公告摘要与 A股 调度 — 默认 15s 自动刷新。</p>

    <div class="toolbar">
      <el-button type="primary" :loading="loading" @click="loadSummary">刷新</el-button>
      <el-switch v-model="autoRefresh" active-text="自动刷新" />
      <el-button @click="probeConnectivity">探测数据源</el-button>
      <el-button @click="router.push('/schedules')">管理调度</el-button>
      <el-button @click="router.push('/stock-announcements')">公告雷达</el-button>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-row v-if="summary" :gutter="16" class="mb">
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">调度任务</div>
          <div class="stat-val">{{ summary.schedules?.running ?? 0 }} / {{ summary.schedules?.total ?? 0 }} 运行中</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">数据过期</div>
          <div class="stat-val warn">{{ summary.data_freshness?.stale_count ?? 0 }}</div>
          <div class="muted small">阈值 {{ summary.data_freshness?.stale_calendar_days ?? 5 }} 交易日</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">AkShare 连通</div>
          <div class="stat-val" :class="{ warn: !summary.connectivity?.ok }">
            {{ summary.connectivity?.ok ? "正常" : "异常" }}
          </div>
          <div class="muted small mono">{{ summary.connectivity?.probe_code }} · {{ summary.connectivity?.latency_ms }}ms</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">公告扫描</div>
          <div class="stat-val">{{ summary.announcements?.items_new ?? 0 }} 新增</div>
          <div class="muted small">{{ summary.announcements?.symbols_scanned ?? 0 }} 标的</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never" class="panel-card">
          <template #header>OHLCV 新鲜度（自选列表）</template>
          <el-table :data="freshnessItems" size="small" max-height="360" stripe empty-text="暂无数据">
            <el-table-column prop="code" label="代码" width="90" />
            <el-table-column prop="symbol" label="标的" width="110" />
            <el-table-column prop="last_bar" label="末根 K 线" width="120" />
            <el-table-column prop="days_old" label="天数" width="70">
              <template #default="{ row }">{{ row.days_old ?? "—" }}</template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.stale ? 'warning' : 'success'">
                  {{ row.stale ? "过期" : "正常" }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card shadow="never" class="panel-card mt">
          <template #header>高影响公告（摘要）</template>
          <el-empty v-if="!topAnnouncements.length" description="暂无高影响公告" />
          <div v-for="item in topAnnouncements" :key="`${item.code}-${item.title}`" class="ann-card">
            <div class="ann-head">
              <strong>{{ item.code }}</strong>
              <el-tag size="small" type="warning">分数 {{ item.score }}</el-tag>
            </div>
            <div class="small">{{ item.title }}</div>
            <div v-if="item.keywords?.length" class="muted small mt">
              {{ item.keywords.slice(0, 4).join(" · ") }}
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never" class="panel-card">
          <template #header>A股 调度任务</template>
          <el-table :data="summary?.schedules?.jobs || []" size="small" max-height="280" stripe>
            <el-table-column prop="id" label="ID" width="130" show-overflow-tooltip />
            <el-table-column prop="name" label="名称" min-width="100" />
            <el-table-column prop="job_type" label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small">{{ row.job_type || "stock_qlib" }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="statusTagType(String(row.status || 'stopped'))">
                  {{ row.status || "stopped" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="last_run_at" label="上次运行" min-width="150" show-overflow-tooltip :formatter="formatTimeCol" />
          </el-table>
        </el-card>

        <el-card v-if="summary?.schedule_alert_recent?.length" shadow="never" class="panel-card mt">
          <template #header>
            <span>调度告警（最近）</span>
            <el-button link type="primary" size="small" @click="router.push('/schedules')">配置规则 →</el-button>
          </template>
          <AlertFeedPanel :items="summary.schedule_alert_recent" :max-height="220" />
        </el-card>

        <el-card shadow="never" class="panel-card mt">
          <template #header>连通性详情</template>
          <el-descriptions v-if="summary?.connectivity" :column="2" size="small" border>
            <el-descriptions-item label="状态">
              <el-tag :type="summary.connectivity.ok ? 'success' : 'danger'" size="small">
                {{ summary.connectivity.ok ? "OK" : "FAIL" }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="探测代码">{{ summary.connectivity.probe_code }}</el-descriptions-item>
            <el-descriptions-item label="来源">{{ summary.connectivity.source || "—" }}</el-descriptions-item>
            <el-descriptions-item label="延迟">{{ summary.connectivity.latency_ms }} ms</el-descriptions-item>
            <el-descriptions-item v-if="summary.connectivity.error" label="错误" :span="2">
              {{ summary.connectivity.error }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}
.mb {
  margin-bottom: 16px;
}
.mt {
  margin-top: 12px;
}
.stat-card {
  text-align: center;
}
.stat-label {
  font-size: 12px;
  color: var(--text-muted);
}
.stat-val {
  font-size: 1.4rem;
  font-weight: 700;
  margin-top: 6px;
}
.stat-val.warn {
  color: #e6a23c;
}
.muted {
  color: var(--text-muted);
}
.small {
  font-size: 12px;
}
.mono {
  font-family: var(--font-mono, monospace);
}
.ann-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
}
.ann-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
</style>
