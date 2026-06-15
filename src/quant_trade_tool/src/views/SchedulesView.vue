<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import { cryptoApi } from "@/api/crypto";
import { stocksApi } from "@/api/stocks";
import { extractError } from "@/api/http";
import AlertFeedPanel from "@/components/AlertFeedPanel.vue";
import ResultPanel from "@/components/ResultPanel.vue";
import { useNotify } from "@/composables/useNotify";

const notify = useNotify();

const marketTab = ref<"crypto" | "astock">("crypto");
const dataDir = computed(() => (marketTab.value === "astock" ? "data/stocks" : "data/crypto"));
const scheduleApi = computed(() => (marketTab.value === "astock" ? stocksApi : cryptoApi));

const jobs = ref<Record<string, unknown>[]>([]);
const loading = ref(false);
const actionLoading = ref("");
const lastRun = ref<unknown>(null);
const error = ref("");
const alertRules = reactive({
  enabled: true,
  on_cycle_error: true,
  on_worker_crash: true,
  consecutive_failures: 3,
  stale_minutes: 0,
  cooldown_minutes: 15,
  webhook_on_alert: true,
  on_cycle_complete: true,
  on_stance_changed: true,
});
const bark = reactive({
  enabled: false,
  device_key: "",
  server: "https://api.day.app",
  device_key_from_env: false,
  device_key_configured: false,
});
const barkTesting = ref(false);
const alertLog = ref<Record<string, unknown>[]>([]);
const rulesSaving = ref(false);
const customRulesJson = ref("[]");
const formatExamples = ref<Record<string, unknown>[]>([]);

const createForm = reactive({
  symbols: ["BTC", "ETH"],
  name: "BTC+ETH 5m",
  id: "",
  timeframe: "5m",
  interval_minutes: 30,
  backfill_days: 90,
  auto_start: false,
  job_type: "analysis" as "analysis" | "news",
});

const stockCreateForm = reactive({
  symbols: ["600519"],
  name: "茅台 qlib",
  id: "",
  interval_minutes: 1440,
  years: 2,
  with_openbb: false,
  use_watchlist: false,
  job_type: "stock_qlib" as "stock_qlib" | "stock_watchlist" | "stock_announcements",
  auto_start: false,
});

const stockAnnouncementsAlerts = reactive({
  on_high_impact: true,
  min_score: 70,
});

watch(marketTab, () => {
  load();
});

watch(
  () => createForm.job_type,
  (t) => {
    if (t === "news") {
      createForm.interval_minutes = 120;
      if (!createForm.name || createForm.name === "BTC+ETH 5m") {
        createForm.name = "舆论扫描";
      }
    } else if (createForm.interval_minutes === 120 && createForm.name === "舆论扫描") {
      createForm.interval_minutes = 30;
      createForm.name = "BTC+ETH 5m";
    }
  },
);

watch(
  () => stockCreateForm.job_type,
  (t) => {
    if (t === "stock_announcements") {
      stockCreateForm.use_watchlist = true;
      stockCreateForm.interval_minutes = 360;
      if (!stockCreateForm.name || stockCreateForm.name === "茅台 qlib") {
        stockCreateForm.name = "公告扫描";
      }
    } else if (t === "stock_watchlist") {
      stockCreateForm.use_watchlist = true;
    } else if (stockCreateForm.interval_minutes === 360 && stockCreateForm.name === "公告扫描") {
      stockCreateForm.interval_minutes = 1440;
      stockCreateForm.name = "茅台 qlib";
    }
  },
);

function jobTypeLabel(t: string) {
  if (t === "news") return "舆论扫描";
  if (t === "stock_watchlist") return "自选刷新";
  if (t === "stock_announcements") return "公告扫描";
  if (t === "stock_qlib") return "A股 qlib";
  return "行情分析";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await scheduleApi.value.schedulesList(dataDir.value);
    jobs.value = (data as { jobs?: Record<string, unknown>[] }).jobs || [];
  } catch (e) {
    error.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

async function createJob() {
  try {
    if (marketTab.value === "astock") {
      await stocksApi.scheduleCreate({
        ...stockCreateForm,
        data_dir: dataDir.value,
        with_ml: stockCreateForm.job_type !== "stock_announcements",
        ml_algorithm: "both",
      });
    } else {
      await cryptoApi.scheduleCreate({
        ...createForm,
        data_dir: dataDir.value,
        with_ml: true,
        ml_algorithm: "both",
      });
    }
    notify.success("任务已创建");
    await load();
  } catch (e) {
    notify.error("创建失败", extractError(e));
  }
}

async function runAction(jobId: string, action: "start" | "stop" | "run-once" | "delete") {
  actionLoading.value = `${jobId}-${action}`;
  try {
    const api = scheduleApi.value;
    const dir = dataDir.value;
    if (action === "start") await api.scheduleStart(jobId, dir);
    else if (action === "stop") await api.scheduleStop(jobId, dir);
    else if (action === "run-once") {
      const { data } = await api.scheduleRunOnce(jobId, dir);
      lastRun.value = data;
      notify.success("已执行一轮");
    } else {
      await ElMessageBox.confirm(`删除任务 ${jobId}?`, "确认");
      await api.scheduleDelete(jobId, dir);
      notify.success("已删除");
    }
    if (action !== "run-once") await load();
  } catch (e) {
    if (e !== "cancel") notify.error("操作失败", extractError(e));
  } finally {
    actionLoading.value = "";
  }
}

async function loadAlertRules() {
  try {
    const { data } = await cryptoApi.scheduleAlertsRulesGet();
    Object.assign(alertRules, data);
    const b = data.bark || {};
    bark.enabled = b.enabled === true || b.enabled === "true" || b.enabled === 1;
    bark.device_key_from_env = Boolean(b.device_key_from_env);
    bark.device_key_configured = Boolean(b.device_key_configured);
    bark.device_key = bark.device_key_from_env ? "" : String(b.device_key || "");
    bark.server = String(b.server || "https://api.day.app");
    if (!bark.device_key_configured && (bark.device_key || bark.device_key_from_env)) {
      bark.device_key_configured = true;
    }
    alertRules.webhook_on_alert = data.webhook_on_alert !== false;
    alertRules.on_cycle_complete = data.on_cycle_complete !== false;
    alertRules.on_stance_changed = data.on_stance_changed !== false;
    const sa = data.stock_announcements || {};
    stockAnnouncementsAlerts.on_high_impact = sa.on_high_impact !== false;
    stockAnnouncementsAlerts.min_score = Number(sa.min_score ?? 70);
    customRulesJson.value = JSON.stringify(data.custom_rules || [], null, 2);
  } catch {
    /* optional */
  }
}

async function loadFormatExamples() {
  try {
    const { data } = await cryptoApi.scheduleAlertsRulesFormat();
    formatExamples.value = data.example_rules || [];
  } catch {
    formatExamples.value = [];
  }
}

function insertExample() {
  if (formatExamples.value.length) {
    customRulesJson.value = JSON.stringify(formatExamples.value, null, 2);
  }
}

async function saveAlertRules() {
  let custom_rules: Record<string, unknown>[] = [];
  try {
    custom_rules = JSON.parse(customRulesJson.value || "[]");
    if (!Array.isArray(custom_rules)) throw new Error("must be array");
  } catch {
    notify.error("JSON 格式错误", "custom_rules 必须是 JSON 数组");
    return;
  }
  rulesSaving.value = true;
  try {
    await cryptoApi.scheduleAlertsRulesSave({
      ...alertRules,
      custom_rules,
      bark: barkPayload(),
      webhook_on_alert: alertRules.webhook_on_alert,
      stock_announcements: {
        on_high_impact: stockAnnouncementsAlerts.on_high_impact,
        min_score: stockAnnouncementsAlerts.min_score,
      },
    });
    notify.success("告警规则已保存");
    await loadAlertLog();
  } catch (e) {
    notify.error("保存失败", extractError(e));
  } finally {
    rulesSaving.value = false;
  }
}

async function loadAlertLog() {
  try {
    const { data } = await cryptoApi.scheduleAlertsLog(30);
    alertLog.value = [...data.items].reverse();
  } catch {
    alertLog.value = [];
  }
}

function barkPayload() {
  const payload: {
    enabled: boolean;
    server: string;
    device_key?: string;
  } = {
    enabled: Boolean(bark.enabled),
    server: String(bark.server || "https://api.day.app").trim() || "https://api.day.app",
  };
  const key = String(bark.device_key || "").trim();
  if (key) payload.device_key = key;
  return payload;
}

async function testBark() {
  const payload = barkPayload();
  if (!bark.device_key_configured && !payload.device_key) {
    notify.warning("未配置 Bark", "请在 .env 设置 BARK_DEVICE_KEY，或填写 Device Key");
    return;
  }
  barkTesting.value = true;
  try {
    await cryptoApi.scheduleAlertsTestBark({ bark: payload });
    notify.success("Bark 测试已发送", "配置已自动保存，请查看手机通知");
  } catch (e) {
    notify.error("Bark 测试失败", extractError(e));
  } finally {
    barkTesting.value = false;
  }
}

async function checkStale() {
  try {
    const { data } = await cryptoApi.scheduleAlertsCheckStale(dataDir.value);
    notify.info(
      data.count ? `检测到 ${data.count} 条卡住任务` : "无卡住任务",
      data.count ? "已写入告警日志" : undefined,
    );
    await loadAlertLog();
  } catch (e) {
    notify.error("检测失败", extractError(e));
  }
}

function statusTagType(status: string) {
  if (status === "running") return "success";
  if (status === "error") return "danger";
  return "info";
}

onMounted(async () => {
  await Promise.all([load(), loadAlertRules(), loadAlertLog(), loadFormatExamples()]);
});
</script>

<template>
  <div>
    <h1 class="page-title">定时任务</h1>
    <p class="page-desc">
      管理 Crypto / A股 调度任务：Crypto 为 K 线 + 分析或舆论扫描；A股 为 qlib 分析、自选刷新或公告扫描。
    </p>

    <el-tabs v-model="marketTab" class="market-tabs">
      <el-tab-pane label="Crypto" name="crypto" />
      <el-tab-pane label="A股" name="astock" />
    </el-tabs>

    <el-row :gutter="20">
      <el-col :span="8">
        <el-card shadow="never" class="panel-card">
          <template #header>新建任务 · {{ marketTab === "astock" ? "A股" : "Crypto" }}</template>
          <el-form v-if="marketTab === 'crypto'" label-width="100px" size="small">
            <el-form-item label="任务类型">
              <el-select v-model="createForm.job_type" style="width: 100%">
                <el-option label="行情分析" value="analysis" />
                <el-option label="舆论扫描" value="news" />
              </el-select>
            </el-form-item>
            <el-form-item label="名称"><el-input v-model="createForm.name" /></el-form-item>
            <el-form-item label="ID"><el-input v-model="createForm.id" placeholder="留空自动生成" /></el-form-item>
            <el-form-item v-if="createForm.job_type === 'analysis'" label="标的">
              <el-select v-model="createForm.symbols" multiple>
                <el-option label="BTC" value="BTC" />
                <el-option label="ETH" value="ETH" />
              </el-select>
            </el-form-item>
            <el-form-item label="间隔(分)"><el-input-number v-model="createForm.interval_minutes" :min="5" /></el-form-item>
            <el-form-item label="自动启动"><el-switch v-model="createForm.auto_start" /></el-form-item>
            <el-button type="primary" @click="createJob">创建</el-button>
            <router-link v-if="createForm.job_type === 'news'" to="/crypto-news" class="news-link">
              舆论雷达配置 →
            </router-link>
          </el-form>
          <el-form v-else label-width="100px" size="small">
            <el-form-item label="任务类型">
              <el-select v-model="stockCreateForm.job_type" style="width: 100%">
                <el-option label="qlib 分析" value="stock_qlib" />
                <el-option label="自选刷新" value="stock_watchlist" />
                <el-option label="公告扫描" value="stock_announcements" />
              </el-select>
            </el-form-item>
            <el-form-item label="名称"><el-input v-model="stockCreateForm.name" /></el-form-item>
            <el-form-item label="ID"><el-input v-model="stockCreateForm.id" placeholder="留空自动生成" /></el-form-item>
            <el-form-item label="自选模式">
              <el-switch
                v-model="stockCreateForm.use_watchlist"
                :disabled="stockCreateForm.job_type === 'stock_announcements'"
              />
              <span class="hint">开启后分析 watchlist 全部标的</span>
            </el-form-item>
            <el-form-item
              v-if="!stockCreateForm.use_watchlist && stockCreateForm.job_type !== 'stock_announcements'"
              label="代码"
            >
              <el-select v-model="stockCreateForm.symbols" multiple filterable allow-create default-first-option>
                <el-option label="600519 茅台" value="600519" />
                <el-option label="000001 平安" value="000001" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="stockCreateForm.job_type !== 'stock_announcements'" label="回溯(年)">
              <el-input-number v-model="stockCreateForm.years" :min="1" :max="10" />
            </el-form-item>
            <el-form-item v-if="stockCreateForm.job_type !== 'stock_announcements'" label="OpenBB">
              <el-switch v-model="stockCreateForm.with_openbb" />
            </el-form-item>
            <el-form-item label="间隔(分)">
              <el-input-number v-model="stockCreateForm.interval_minutes" :min="60" :step="60" />
              <span class="hint">建议 1440（收盘后每日）</span>
            </el-form-item>
            <el-form-item label="自动启动"><el-switch v-model="stockCreateForm.auto_start" /></el-form-item>
            <el-button type="primary" @click="createJob">创建</el-button>
            <router-link
              v-if="stockCreateForm.job_type === 'stock_announcements'"
              to="/stock-announcements"
              class="news-link"
            >
              公告雷达配置 →
            </router-link>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <span>任务列表 ({{ jobs.length }})</span>
            <el-button link type="primary" :loading="loading" @click="load">刷新</el-button>
          </template>
          <el-table v-loading="loading" :data="jobs" size="small">
            <el-table-column prop="id" label="ID" width="140" />
            <el-table-column prop="name" label="名称" />
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.job_type === 'news' || row.job_type === 'stock_announcements' ? 'warning' : ''">
                  {{ jobTypeLabel(String(row.job_type || "analysis")) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="statusTagType(String(row.status || 'stopped'))" size="small">
                  {{ row.status || "stopped" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="last_error" label="最近错误" min-width="120" show-overflow-tooltip />
            <el-table-column prop="run_count" label="次数" width="64" />
            <el-table-column label="操作" width="280">
              <template #default="{ row }">
                <el-button
                  size="small"
                  :loading="actionLoading === `${row.id}-run-once`"
                  @click="runAction(row.id as string, 'run-once')"
                >跑一次</el-button>
                <el-button
                  v-if="row.status !== 'running'"
                  size="small"
                  type="success"
                  @click="runAction(row.id as string, 'start')"
                >启动</el-button>
                <el-button v-else size="small" type="warning" @click="runAction(row.id as string, 'stop')">停止</el-button>
                <el-button size="small" type="danger" @click="runAction(row.id as string, 'delete')">删</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
        <el-card shadow="never" class="panel-card mt">
          <template #header>调度告警规则</template>
          <el-form label-width="140px" size="small">
            <el-form-item label="启用告警"><el-switch v-model="alertRules.enabled" /></el-form-item>
            <el-form-item label="周期失败"><el-switch v-model="alertRules.on_cycle_error" /></el-form-item>
            <el-form-item label="线程崩溃"><el-switch v-model="alertRules.on_worker_crash" /></el-form-item>
            <el-form-item label="连续失败阈值">
              <el-input-number v-model="alertRules.consecutive_failures" :min="0" :max="20" />
              <span class="hint">0=关闭</span>
            </el-form-item>
            <el-form-item label="卡住检测(分)">
              <el-input-number v-model="alertRules.stale_minutes" :min="0" :max="1440" />
              <span class="hint">0=关闭；运营看板刷新时也会检测</span>
            </el-form-item>
            <el-form-item label="冷却(分)">
              <el-input-number v-model="alertRules.cooldown_minutes" :min="1" :max="1440" />
            </el-form-item>
            <el-button type="primary" :loading="rulesSaving" @click="saveAlertRules">保存规则</el-button>
            <el-button @click="checkStale">检测卡住</el-button>
          </el-form>
          <el-divider content-position="left">手机推送</el-divider>
          <el-form label-width="140px" size="small">
            <el-form-item label="周期完成推送">
              <el-switch v-model="alertRules.on_cycle_complete" :disabled="!bark.enabled || !bark.device_key_configured" />
              <span class="hint">每轮分析成功跑完后推送到 Bark（需开启下方 Bark 推送）</span>
            </el-form-item>
            <el-form-item label="立场变化">
              <el-switch v-model="alertRules.on_stance_changed" />
              <span class="hint">报告 stance 变化时告警（A股/Crypto 均适用）</span>
            </el-form-item>
            <el-form-item label="Bark 推送">
              <el-switch
                v-model="bark.enabled"
                :active-value="true"
                :inactive-value="false"
                :disabled="!bark.device_key_configured"
              />
              <span v-if="bark.device_key_configured" class="hint">开启后，定时分析告警推送到手机</span>
              <span v-else class="hint">请先在 .env 配置 BARK_DEVICE_KEY，或在下方填写 Key</span>
            </el-form-item>
            <el-form-item v-if="bark.device_key_from_env" label="Device Key">
              <span class="hint">已从 <code>.env</code> 读取 <code>BARK_DEVICE_KEY</code>（不在页面展示）</span>
            </el-form-item>
            <el-form-item v-else label="Device Key">
              <el-input
                v-model="bark.device_key"
                placeholder="Bark App 中的 Key，或写入 .env 的 BARK_DEVICE_KEY"
                show-password
                style="max-width: 420px"
                @input="bark.device_key_configured = Boolean(bark.device_key.trim())"
              />
            </el-form-item>
            <el-form-item label="服务器">
              <el-input v-model="bark.server" placeholder="https://api.day.app" style="max-width: 420px" />
              <span class="hint">自建 Bark 可改域名</span>
            </el-form-item>
            <el-form-item label=" ">
              <el-button :loading="barkTesting" @click="testBark">测试 Bark</el-button>
              <span class="hint">测试成功会自动保存；Key 优先使用 .env</span>
            </el-form-item>
            <el-form-item label="Webhook 推送">
              <el-switch v-model="alertRules.webhook_on_alert" />
              <span class="hint">使用「Crypto 运营」里配置的 Webhook URL</span>
            </el-form-item>
          </el-form>

          <el-divider content-position="left">A股 公告告警</el-divider>
          <el-form label-width="140px" size="small">
            <el-form-item label="高影响公告">
              <el-switch v-model="stockAnnouncementsAlerts.on_high_impact" />
              <span class="hint">公告扫描周期完成后，分数超阈值时 Bark/Webhook 告警</span>
            </el-form-item>
            <el-form-item label="最低分数">
              <el-input-number v-model="stockAnnouncementsAlerts.min_score" :min="40" :max="100" />
            </el-form-item>
          </el-form>

          <el-collapse class="mt">
            <el-collapse-item title="自定义规则：条件格式说明" name="format">
              <div class="format-doc">
                <p>在下方 JSON 数组中配置 <code>custom_rules</code>。每个规则在调度周期成功后，按标的的 <strong>stance / action / symbol</strong> 匹配。</p>
                <ul>
                  <li><strong>conditions</strong>：<code>{"field","op","value"}</code> — field: symbol/stance/action/new_bars；op: eq/neq/in/not_in/contains/regex/gt/gte/lt/lte</li>
                  <li><strong>logic</strong>：<code>and</code>（默认）或 <code>or</code> — 组合 conditions</li>
                  <li><strong>symbol_scope</strong>：<code>any_symbol</code>（任一标的命中）或 <code>all_symbols</code>（全部标的都命中）</li>
                  <li><strong>job_ids</strong>：空 = 全部任务；否则只监听指定调度 id</li>
                  <li><strong>message</strong>：占位符含 <code>{var_pct} {var_usdt}</code> 等</li>
                  <li><strong>VaR 字段</strong>：<code>var_pct</code> / <code>var_usdt</code> / <code>var_99_pct</code> — 需在保存的 JSON 根对象加 <code>var.enabled: true</code>（见文档）</li>
                  <li><strong>内置 VaR 超限</strong>：<code>var.on_symbol_var_breach</code> + <code>max_var_pct</code>（如 0.05）</li>
                </ul>
                <p class="hint">完整说明见 <code>docs/schedule-alert-custom-rules.md</code> · API <code>GET .../alerts/rules/format</code></p>
              </div>
            </el-collapse-item>
          </el-collapse>

          <div class="custom-toolbar mt">
            <span class="small muted">custom_rules JSON</span>
            <el-button size="small" @click="insertExample">填入示例</el-button>
          </div>
          <el-input
            v-model="customRulesJson"
            type="textarea"
            :rows="10"
            class="mono mt"
            placeholder='[{"id":"btc-bull","conditions":[{"field":"symbol","op":"eq","value":"BTC"},{"field":"stance","op":"eq","value":"看涨"}]}]'
          />
        </el-card>

        <el-card shadow="never" class="panel-card mt">
          <template #header>
            <span>最近告警</span>
            <el-button link type="primary" size="small" @click="loadAlertLog">刷新</el-button>
          </template>
          <AlertFeedPanel :items="alertLog" />
        </el-card>

        <ResultPanel v-if="lastRun" title="最近一次 run-once" :result="lastRun" />
        <el-alert v-if="error" class="mt" type="error" :title="error" show-icon />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.market-tabs {
  margin-bottom: 12px;
}
.mt {
  margin-top: 12px;
}
.hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-muted);
}
.news-link {
  display: block;
  margin-top: 10px;
  font-size: 13px;
  color: var(--el-color-primary);
  text-decoration: none;
}
.news-link:hover {
  text-decoration: underline;
}
.format-doc {
  font-size: 13px;
  line-height: 1.55;
}
.format-doc ul {
  margin: 8px 0;
  padding-left: 20px;
}
.custom-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mono :deep(textarea) {
  font-family: var(--font-mono, monospace);
  font-size: 12px;
}
</style>
