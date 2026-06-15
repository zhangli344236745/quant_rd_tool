<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  stocksApi,
  type StockAnnouncementDigest,
  type StockAnnouncementItem,
} from "@/api/stocks";
import { extractError } from "@/api/http";

const loading = ref(false);
const scanning = ref(false);
const error = ref("");
const digest = ref<StockAnnouncementDigest | null>(null);
const items = ref<StockAnnouncementItem[]>([]);

const scanForm = ref({
  use_watchlist: true,
  notice_limit: 15,
  min_score: 40,
});

const digestHeadline = computed(() => {
  if (!digest.value) return null;
  const n = digest.value.items_new ?? digest.value.top_items?.length ?? 0;
  if (!n && !digest.value.generated_at) return null;
  return `扫描 ${digest.value.symbols_scanned ?? 0} 只，新增 ${n} 条重点公告`;
});

function formatTime(ts: string | undefined) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function scoreTagType(score: number | undefined) {
  if ((score ?? 0) >= 80) return "danger";
  if ((score ?? 0) >= 60) return "warning";
  return "info";
}

async function loadDigest() {
  try {
    const { data } = await stocksApi.announcementsDigest();
    digest.value = data.digest || null;
  } catch {
    digest.value = null;
  }
}

async function loadItems() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await stocksApi.announcementsItems({ limit: 50 });
    items.value = data.items || [];
    await loadDigest();
  } catch (e) {
    error.value = extractError(e);
    items.value = [];
  } finally {
    loading.value = false;
  }
}

async function runScan() {
  scanning.value = true;
  try {
    const { data } = await stocksApi.announcementsScan({
      use_watchlist: scanForm.value.use_watchlist,
      notice_limit: scanForm.value.notice_limit,
      min_score: scanForm.value.min_score,
    });
    if (data.error) {
      ElMessage.warning(data.error);
    } else {
      ElMessage.success(`扫描完成，新增 ${data.items_new ?? 0} 条`);
    }
    if (data.digest) digest.value = data.digest;
    await loadItems();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    scanning.value = false;
  }
}

onMounted(loadItems);
</script>

<template>
  <div>
    <h1 class="page-title">A股公告雷达</h1>
    <p class="page-desc">
      对自选或指定标的扫描公告/新闻，按关键词规则打分（立案、减持、业绩预增等），辅助选股器「高影响公告」筛选。
    </p>

    <el-card shadow="never" class="panel-card">
      <el-form :inline="true" size="small">
        <el-form-item label="仅自选">
          <el-switch v-model="scanForm.use_watchlist" />
        </el-form-item>
        <el-form-item label="最低分">
          <el-input-number v-model="scanForm.min_score" :min="0" :max="100" />
        </el-form-item>
        <el-form-item label="每只条数">
          <el-input-number v-model="scanForm.notice_limit" :min="5" :max="50" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="scanning" @click="runScan">立即扫描</el-button>
          <el-button :loading="loading" @click="loadItems">刷新</el-button>
        </el-form-item>
      </el-form>

      <div v-if="digestHeadline" class="digest-banner mt">
        <span class="digest-text">{{ digestHeadline }}</span>
        <span v-if="digest?.generated_at" class="muted small">· {{ formatTime(digest.generated_at) }}</span>
      </div>
      <p v-else-if="!loading" class="muted small mt">暂无 digest，点击「立即扫描」拉取公告。</p>
    </el-card>

    <el-card shadow="never" class="panel-card mt">
      <template #header>公告时间线 ({{ items.length }})</template>
      <el-empty v-if="!loading && !items.length" description="暂无公告条目" />
      <el-timeline v-else v-loading="loading">
        <el-timeline-item
          v-for="(item, idx) in items"
          :key="`${item.code}-${item.title}-${idx}`"
          :timestamp="formatTime(item.published || item.ts)"
          placement="top"
        >
          <div class="item-head">
            <el-tag size="small" type="info" class="mr">{{ item.code }}</el-tag>
            <el-tag v-if="item.score != null" size="small" :type="scoreTagType(item.score)" class="mr">
              {{ item.score }} 分
            </el-tag>
            <el-tag v-for="kw in item.keywords || []" :key="kw" size="small" effect="plain" class="mr">
              {{ kw }}
            </el-tag>
            <span class="item-title">{{ item.title }}</span>
          </div>
          <p v-if="item.category" class="muted small">{{ item.category }}</p>
        </el-timeline-item>
      </el-timeline>
      <el-alert v-if="error" type="error" :title="error" show-icon class="mt" />
    </el-card>
  </div>
</template>

<style scoped>
.page-title {
  margin: 0 0 8px;
  font-size: 22px;
}
.page-desc {
  margin: 0 0 16px;
  color: var(--text-muted);
  font-size: 14px;
}
.panel-card {
  margin-bottom: 12px;
}
.mt {
  margin-top: 12px;
}
.mr {
  margin-right: 8px;
}
.muted {
  color: var(--text-muted);
}
.small {
  font-size: 12px;
}
.digest-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.digest-text {
  font-size: 14px;
}
.item-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.item-title {
  font-weight: 600;
  font-size: 14px;
}
</style>
