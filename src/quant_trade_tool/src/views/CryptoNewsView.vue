<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  cryptoApi,
  type CryptoNewsDigest,
  type CryptoNewsItem,
  type CryptoNewsSearchUsage,
} from "@/api/crypto";
import { extractError } from "@/api/http";

const newsDataDir = "data";

const loading = ref(false);
const scanning = ref(false);
const error = ref("");
const digest = ref<CryptoNewsDigest | null>(null);
const items = ref<CryptoNewsItem[]>([]);
const expandedIds = ref<Set<string>>(new Set());

const configVisible = ref(false);
const configSaving = ref(false);
const configForm = ref({
  enabled: true,
  min_score: 40,
  llm_top_n: 5,
  attach_to_analysis_cycle: true,
  web_search_enabled: false,
  web_search_provider: "auto" as "auto" | "tavily" | "serpapi" | "none",
  web_search_max_queries: 3,
  web_search_max_results: 5,
  web_search_monthly_limit: 150,
});

const searchProviders = ref({
  tavily_configured: false,
  serpapi_configured: false,
  active_provider: null as string | null,
});

const searchUsage = ref<CryptoNewsSearchUsage | null>(null);

const usagePercent = computed(() => {
  const u = searchUsage.value;
  if (!u?.monthly_query_limit || u.monthly_query_limit <= 0) return 0;
  return Math.min(100, Math.round(((u.queries_used ?? 0) / u.monthly_query_limit) * 100));
});

const usageStatus = computed(() => {
  const u = searchUsage.value;
  if (!u?.monthly_query_limit) return "";
  return `${u.queries_used ?? 0} / ${u.monthly_query_limit} 次查询（${u.month ?? ""}）`;
});

function sourceLabel(sourceId: string | undefined) {
  if (!sourceId) return "RSS";
  if (sourceId.startsWith("web_search:")) {
    const p = sourceId.split(":")[1] || "web";
    return p === "tavily" ? "Tavily" : p === "serpapi" ? "SerpAPI" : "联网";
  }
  return sourceId;
}

function isWebSearchSource(sourceId: string | undefined) {
  return Boolean(sourceId?.startsWith("web_search:"));
}

const stanceLabel: Record<string, string> = {
  bullish: "偏多",
  bearish: "偏空",
  neutral: "中性",
  mixed: "分化",
};

function impactTagType(impact: string | undefined) {
  if (impact === "bullish") return "success";
  if (impact === "bearish") return "danger";
  if (impact === "mixed") return "warning";
  return "info";
}

function impactLabel(item: CryptoNewsItem) {
  const impact = item.advice?.impact || item.impact_direction || "neutral";
  return stanceLabel[impact] || impact;
}

function itemImpact(item: CryptoNewsItem) {
  return item.advice?.impact || item.impact_direction || "neutral";
}

function itemKey(item: CryptoNewsItem, index: number) {
  return item.id || item.link || `${item.title}-${index}`;
}

function formatTime(ts: string | undefined) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function pctConf(v: number | undefined) {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}

const digestHeadline = computed(() => {
  if (!digest.value || digest.value.empty) return null;
  const stance = stanceLabel[digest.value.market_stance] || digest.value.market_stance;
  const n = digest.value.top_items?.length ?? 0;
  return `市场舆论：${stance}（${n} 条重点）`;
});

async function loadConfig() {
  try {
    const { data } = await cryptoApi.newsConfigGet(newsDataDir);
    configForm.value = {
      enabled: data.enabled !== false,
      min_score: data.min_score ?? 40,
      llm_top_n: data.llm_top_n ?? 5,
      attach_to_analysis_cycle: data.attach_to_analysis_cycle !== false,
      web_search_enabled: data.web_search?.enabled === true,
      web_search_provider: data.web_search?.provider ?? "auto",
      web_search_max_queries: data.web_search?.max_queries_per_cycle ?? 3,
      web_search_max_results: data.web_search?.max_results_per_query ?? 5,
      web_search_monthly_limit: data.web_search?.monthly_query_limit ?? 150,
    };
    searchProviders.value = {
      tavily_configured: data.search_providers?.tavily_configured === true,
      serpapi_configured: data.search_providers?.serpapi_configured === true,
      active_provider: data.search_providers?.active_provider ?? null,
    };
    searchUsage.value = data.search_usage ?? null;
  } catch {
    /* defaults */
  }
}

async function loadSearchUsage() {
  try {
    const { data } = await cryptoApi.newsSearchUsage(newsDataDir);
    searchUsage.value = data;
  } catch {
    searchUsage.value = null;
  }
}

async function saveConfig() {
  configSaving.value = true;
  try {
    await cryptoApi.newsConfigSave({
      enabled: configForm.value.enabled,
      min_score: configForm.value.min_score,
      llm_top_n: configForm.value.llm_top_n,
      attach_to_analysis_cycle: configForm.value.attach_to_analysis_cycle,
      web_search: {
        enabled: configForm.value.web_search_enabled,
        provider: configForm.value.web_search_provider,
        max_queries_per_cycle: configForm.value.web_search_max_queries,
        max_results_per_query: configForm.value.web_search_max_results,
        monthly_query_limit: configForm.value.web_search_monthly_limit,
      },
    });
    await loadConfig();
    await loadSearchUsage();
    ElMessage.success("舆论扫描配置已保存");
    configVisible.value = false;
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    configSaving.value = false;
  }
}

async function loadDigest() {
  try {
    const { data } = await cryptoApi.newsDigest(newsDataDir);
    digest.value = data;
  } catch {
    digest.value = null;
  }
}

async function loadItems() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await cryptoApi.newsItems({ data_dir: newsDataDir, limit: 50 });
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
    const { data } = await cryptoApi.newsScan({ data_dir: newsDataDir });
    if (data.digest) digest.value = data.digest;
    ElMessage.success(`扫描完成，处理 ${data.items_processed ?? 0} 条`);
    await loadItems();
    await loadSearchUsage();
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    scanning.value = false;
  }
}

function toggleExpand(key: string) {
  const next = new Set(expandedIds.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  expandedIds.value = next;
}

onMounted(async () => {
  await loadConfig();
  await loadSearchUsage();
  await loadItems();
});
</script>

<template>
  <div>
    <h1 class="page-title">舆论雷达</h1>
    <p class="page-desc">
      国际宏观与 crypto RSS 舆情 + 可选联网搜索（Tavily/SerpAPI）：规则打分 + LLM 解读；可手动扫描或配置定时「舆论扫描」任务。
    </p>

    <el-card shadow="never" class="panel-card">
      <div class="toolbar">
        <el-button type="primary" :loading="scanning" @click="runScan">立即扫描</el-button>
        <el-button :loading="loading" @click="loadItems">刷新</el-button>
        <el-button @click="configVisible = true">配置</el-button>
      </div>

      <div v-if="searchUsage?.monthly_query_limit" class="usage-bar mt">
        <div class="usage-head">
          <span class="small">联网搜索本月用量</span>
          <span class="small muted">{{ usageStatus }}</span>
        </div>
        <el-progress
          :percentage="usagePercent"
          :status="searchUsage.limit_reached ? 'exception' : usagePercent >= 85 ? 'warning' : undefined"
          :stroke-width="10"
        />
        <p v-if="searchUsage.limit_reached" class="hint warn">
          已达月度上限，联网搜索已暂停（RSS 扫描不受影响）。可在配置中调高限额或下月自动重置。
        </p>
      </div>

      <div v-if="digestHeadline" class="digest-banner mt">
        <el-tag
          :type="impactTagType(digest?.market_stance)"
          size="small"
          class="mr"
        >
          {{ stanceLabel[digest!.market_stance!] || digest!.market_stance }}
        </el-tag>
        <span class="digest-text">{{ digestHeadline }}</span>
        <span v-if="digest?.generated_at" class="muted small">
          · {{ formatTime(digest.generated_at) }}
        </span>
      </div>
      <p v-else-if="!loading" class="muted small mt">暂无 digest，点击「立即扫描」拉取 RSS 并生成摘要。</p>
    </el-card>

    <el-card shadow="never" class="panel-card mt">
      <template #header>
        <span>舆情时间线 ({{ items.length }})</span>
      </template>

      <el-empty v-if="!loading && !items.length" description="暂无新闻条目" />

      <el-timeline v-else v-loading="loading">
        <el-timeline-item
          v-for="(item, idx) in items"
          :key="itemKey(item, idx)"
          :timestamp="formatTime(item.published)"
          placement="top"
        >
          <div class="news-item">
            <div class="news-head">
              <el-tag :type="impactTagType(itemImpact(item))" size="small" class="mr">
                {{ impactLabel(item) }}
              </el-tag>
              <el-tag v-if="item.score != null" size="small" type="info" class="mr">
                {{ item.score }} 分
              </el-tag>
              <el-tag v-if="item.category" size="small" effect="plain" class="mr">
                {{ item.category }}
              </el-tag>
              <el-tag
                v-if="item.source_id"
                size="small"
                :type="isWebSearchSource(item.source_id) ? 'warning' : 'info'"
                effect="plain"
                class="mr"
              >
                {{ sourceLabel(item.source_id) }}
              </el-tag>
              <a
                v-if="item.link"
                :href="item.link"
                target="_blank"
                rel="noopener"
                class="news-title"
              >
                {{ item.title }}
              </a>
              <span v-else class="news-title">{{ item.title }}</span>
            </div>

            <p v-if="item.summary" class="news-summary muted small">
              {{ item.summary }}
            </p>

            <div v-if="item.advice?.headline || item.advice?.advice" class="advice-block">
              <p v-if="item.advice?.headline" class="advice-headline">
                {{ item.advice.headline }}
                <span v-if="item.advice.confidence != null" class="muted small">
                  · 置信 {{ pctConf(item.advice.confidence) }}
                </span>
              </p>
              <el-button
                v-if="item.advice?.advice"
                link
                type="primary"
                size="small"
                @click="toggleExpand(itemKey(item, idx))"
              >
                {{ expandedIds.has(itemKey(item, idx)) ? "收起建议" : "展开建议" }}
              </el-button>
              <p
                v-if="expandedIds.has(itemKey(item, idx)) && item.advice?.advice"
                class="advice-body small"
              >
                {{ item.advice.advice }}
              </p>
              <p
                v-if="expandedIds.has(itemKey(item, idx)) && item.advice?.risk_note"
                class="risk-note small"
              >
                {{ item.advice.risk_note }}
              </p>
            </div>

            <div v-if="item.symbols?.length || item.advice?.affected_symbols?.length" class="symbols">
              <el-tag
                v-for="sym in (item.advice?.affected_symbols || item.symbols || [])"
                :key="sym"
                size="small"
                effect="plain"
                class="sym-tag"
              >
                {{ sym }}
              </el-tag>
            </div>
          </div>
        </el-timeline-item>
      </el-timeline>

      <el-alert v-if="error" type="error" :title="error" show-icon class="mt" />
    </el-card>

    <el-dialog v-model="configVisible" title="舆论扫描配置" width="480px">
      <el-form label-width="140px" size="small">
        <el-form-item label="启用">
          <el-switch v-model="configForm.enabled" />
        </el-form-item>
        <el-form-item label="最低分数">
          <el-input-number v-model="configForm.min_score" :min="0" :max="100" />
          <span class="hint">达到阈值才进入 LLM 解读</span>
        </el-form-item>
        <el-form-item label="LLM Top N">
          <el-input-number v-model="configForm.llm_top_n" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="附加到分析周期">
          <el-switch v-model="configForm.attach_to_analysis_cycle" />
          <span class="hint">Crypto 行情分析报告内嵌 news_digest</span>
        </el-form-item>
        <el-divider content-position="left">联网搜索（可选）</el-divider>
        <el-form-item label="启用联网搜索">
          <el-switch v-model="configForm.web_search_enabled" />
          <span class="hint">需配置 TAVILY_API_KEY 或 SERPAPI_API_KEY（.env）</span>
        </el-form-item>
        <el-form-item v-if="configForm.web_search_enabled" label="搜索提供商">
          <el-select v-model="configForm.web_search_provider" style="width: 100%">
            <el-option label="自动（优先 Tavily）" value="auto" />
            <el-option label="Tavily" value="tavily" :disabled="!searchProviders.tavily_configured" />
            <el-option label="SerpAPI" value="serpapi" :disabled="!searchProviders.serpapi_configured" />
            <el-option label="关闭" value="none" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="configForm.web_search_enabled" label="每轮查询数">
          <el-input-number v-model="configForm.web_search_max_queries" :min="1" :max="10" />
          <span class="hint">控制 API 成本；默认 3 条内置宏观查询</span>
        </el-form-item>
        <el-form-item v-if="configForm.web_search_enabled" label="每查询结果数">
          <el-input-number v-model="configForm.web_search_max_results" :min="1" :max="10" />
        </el-form-item>
        <el-form-item v-if="configForm.web_search_enabled" label="月度查询上限">
          <el-input-number v-model="configForm.web_search_monthly_limit" :min="0" :max="100000" />
          <span class="hint">0 = 不限制；默认 150 次/月</span>
        </el-form-item>
        <p
          v-if="configForm.web_search_enabled && !searchProviders.tavily_configured && !searchProviders.serpapi_configured"
          class="hint warn"
        >
          未检测到搜索 API Key，联网搜索将在扫描时跳过。
        </p>
        <p v-else-if="searchProviders.active_provider" class="hint">
          当前可用：{{ searchProviders.active_provider }}
        </p>
      </el-form>
      <template #footer>
        <el-button @click="configVisible = false">取消</el-button>
        <el-button type="primary" :loading="configSaving" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mt {
  margin-top: 16px;
}
.mr {
  margin-right: 8px;
}
.toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
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
.news-item {
  padding-bottom: 4px;
}
.news-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.news-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-color-primary);
  text-decoration: none;
}
.news-title:hover {
  text-decoration: underline;
}
.news-summary {
  margin: 6px 0 0;
  line-height: 1.45;
}
.advice-block {
  margin-top: 8px;
}
.advice-headline {
  margin: 0 0 4px;
  font-size: 13px;
}
.advice-body {
  margin: 6px 0 0;
  line-height: 1.5;
  color: var(--text-muted);
}
.risk-note {
  margin: 4px 0 0;
  color: var(--el-color-warning);
  font-style: italic;
}
.symbols {
  margin-top: 6px;
}
.sym-tag {
  margin-right: 4px;
}
.muted.small {
  font-size: 12px;
  color: var(--text-muted);
}
.usage-bar {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}
.usage-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}
.hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-muted);
}
.hint.warn {
  display: block;
  margin: 8px 0 0;
  color: var(--el-color-warning);
}
</style>
