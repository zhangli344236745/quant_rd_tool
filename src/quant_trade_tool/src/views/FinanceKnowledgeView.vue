<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { extractError } from "@/api/http";
import {
  knowledgeApi,
  type KbCitation,
  type KbDocument,
  type KbStatus,
} from "@/api/knowledge";

type ChatRow = {
  role: "user" | "assistant";
  content: string;
  citations?: KbCitation[];
  backend?: string;
};

const lastBackend = ref<string | null>(null);

const loading = ref(false);
const syncing = ref(false);
const uploading = ref(false);
const sending = ref(false);
const status = ref<KbStatus | null>(null);
const documents = ref<KbDocument[]>([]);
const tagFilter = ref("");
const sessionId = ref<string | undefined>();
const input = ref("");
const messages = ref<ChatRow[]>([]);
const cursorReady = computed(
  () =>
    Boolean(
      status.value?.cursor_configured &&
        (status.value?.cursor_api_available ?? status.value?.cursor_sdk_available),
    ),
);

const backendLabel: Record<string, string> = {
  cloud_sdk: "Cloud SDK",
  cloud_rest: "Cloud REST",
  rag: "检索摘要",
  openai: "OpenAI",
  pending: "处理中",
};

const statusLine = computed(() => {
  const s = status.value;
  if (!s) return "加载中…";
  const sync = s.last_sync_at ? new Date(s.last_sync_at).toLocaleString() : "未同步";
  const rest = s.cursor_api_check;
  const sdk = s.cursor_sdk_check;
  const mode = s.kb_agent_backend || "auto";
  let cursor = "Cursor 未配置";
  if (s.cursor_configured) {
    const parts: string[] = [];
    if (rest?.ok) {
      const who = rest.user_email ? ` (${rest.user_email})` : "";
      parts.push(`REST 已连通${who}`);
    } else if (rest?.error) {
      parts.push(`REST: ${rest.error}`);
    }
    if (s.cursor_sdk_installed) {
      if (sdk?.ok) parts.push("SDK 已连通");
      else if (sdk?.error) parts.push(`SDK: ${sdk.error}`);
    }
    cursor = parts.length ? parts.join(" · ") : "API 不可用";
    if (mode !== "auto") cursor += ` · 模式 ${mode}`;
  }
  const last = lastBackend.value
    ? ` · 上次回复: ${backendLabel[lastBackend.value] || lastBackend.value}`
    : "";
  return `${s.doc_count} 文档 · ${s.chunk_count} 块 · 上次同步 ${sync} · ${cursor}${last}`;
});

async function loadStatus() {
  const { data } = await knowledgeApi.status();
  status.value = data;
}

async function loadDocuments() {
  loading.value = true;
  try {
    const { data } = await knowledgeApi.documents({
      tag: tagFilter.value || undefined,
      page_size: 100,
    });
    documents.value = data.items;
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

async function syncProject() {
  syncing.value = true;
  try {
    const { data } = await knowledgeApi.syncProject();
    ElMessage.success(`同步完成：新增/更新 ${data.ingested}，跳过 ${data.skipped}`);
    await Promise.all([loadStatus(), loadDocuments()]);
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    syncing.value = false;
  }
}

async function onUpload(file: File) {
  uploading.value = true;
  try {
    const { data } = await knowledgeApi.upload(file);
    if (data.ok) {
      ElMessage.success("上传成功");
      await Promise.all([loadStatus(), loadDocuments()]);
    } else {
      ElMessage.warning(data.warning || "上传未完成");
    }
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    uploading.value = false;
  }
  return false;
}

async function deleteDoc(doc: KbDocument) {
  try {
    await ElMessageBox.confirm(`删除「${doc.title}」？`, "确认", { type: "warning" });
    await knowledgeApi.deleteDocument(doc.id);
    ElMessage.success("已删除");
    await Promise.all([loadStatus(), loadDocuments()]);
  } catch (e) {
    if (e !== "cancel") ElMessage.error(extractError(e));
  }
}

async function sendMessage() {
  const text = input.value.trim();
  if (!text || sending.value) return;
  input.value = "";
  messages.value.push({ role: "user", content: text });
  sending.value = true;

  // Always use non-stream Cloud REST (POST /v1/agents via backend); stream was flaky in browser.
  messages.value.push({
    role: "assistant",
    content: cursorReady.value ? "Cloud Agent 思考中，约需 15–40 秒…" : "处理中…",
    citations: [],
  });
  const idx = messages.value.length - 1;

  try {
    const { data } = await knowledgeApi.chat({ message: text, session_id: sessionId.value });
    sessionId.value = data.session_id;
    messages.value[idx] = {
      role: "assistant",
      content: data.answer,
      citations: data.citations,
      backend: data.backend,
    };
    lastBackend.value = data.backend || null;
    if (data.backend === "rag") {
      const detail = data.backend_error ? `：${data.backend_error}` : "";
      ElMessage.warning(`已降级为检索摘要（Cloud Agent 未响应${detail}）`);
    } else if (data.backend === "cloud_sdk" || data.backend === "cloud_rest") {
      ElMessage.success({
        message:
          data.backend === "cloud_sdk" ? "Cloud SDK 回复完成" : "Cloud REST 回复完成",
        duration: 2000,
      });
    }
  } catch (e) {
    ElMessage.error(extractError(e));
    messages.value.pop();
  } finally {
    sending.value = false;
  }
}

function newChat() {
  sessionId.value = undefined;
  messages.value = [];
  lastBackend.value = null;
}

onMounted(async () => {
  await loadStatus();
  await loadDocuments();
});
</script>

<template>
  <div class="kb-page">
    <header class="kb-header">
      <div>
        <h1>金融知识库</h1>
        <p class="mono status-line">{{ statusLine }}</p>
      </div>
      <div class="header-actions">
        <el-button size="small" @click="newChat">新对话</el-button>
        <el-button size="small" type="primary" :loading="syncing" @click="syncProject">
          同步项目数据
        </el-button>
      </div>
    </header>

    <div class="kb-layout">
      <aside class="doc-panel">
        <div class="panel-toolbar">
          <el-input
            v-model="tagFilter"
            size="small"
            placeholder="标签过滤"
            clearable
            @change="loadDocuments"
          />
          <el-upload :show-file-list="false" :before-upload="onUpload" accept=".md,.txt,.pdf">
            <el-button size="small" :loading="uploading">上传</el-button>
          </el-upload>
        </div>
        <el-scrollbar v-loading="loading" class="doc-list">
          <div v-for="doc in documents" :key="doc.id" class="doc-item">
            <div class="doc-title">{{ doc.title }}</div>
            <div class="doc-meta mono">
              {{ doc.source }} · {{ doc.chunk_count }} 块
              <span v-if="doc.tags?.length"> · {{ doc.tags.join(", ") }}</span>
            </div>
            <el-button link type="danger" size="small" @click="deleteDoc(doc)">删除</el-button>
          </div>
          <el-empty v-if="!loading && documents.length === 0" description="暂无文档，请先同步或上传" />
        </el-scrollbar>
      </aside>

      <section class="chat-panel">
        <el-scrollbar class="chat-scroll">
          <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
            <div class="bubble">{{ m.content }}</div>
            <div v-if="m.backend && m.role === 'assistant'" class="backend-tag mono">
              {{ backendLabel[m.backend] || m.backend }}
            </div>
            <div v-if="m.citations?.length" class="citations">
              <el-tag
                v-for="c in m.citations"
                :key="c.chunk_id"
                size="small"
                type="info"
                class="cite-tag"
                :title="c.snippet"
              >
                {{ c.title }}
              </el-tag>
            </div>
          </div>
          <el-empty v-if="messages.length === 0" description="提问开始对话，例如：BTC 最新报告要点" />
        </el-scrollbar>

        <div class="composer">
          <el-input
            v-model="input"
            type="textarea"
            :rows="3"
            placeholder="输入问题…"
            :disabled="sending"
            @keydown.ctrl.enter="sendMessage"
          />
          <el-button
            type="primary"
            :loading="sending"
            :disabled="!input.trim()"
            @click="sendMessage"
          >
            发送
          </el-button>
        </div>
        <p class="disclaimer mono">仅供参考，不构成投资建议。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.kb-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: calc(100vh - 120px);
}

.kb-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.kb-header h1 {
  margin: 0 0 4px;
  font-size: 1.25rem;
}

.status-line {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
}

.kb-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  flex: 1;
  min-height: 0;
}

.doc-panel,
.chat-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(18, 23, 31, 0.5);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.panel-toolbar {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid var(--border);
}

.doc-list {
  flex: 1;
  padding: 8px 12px;
}

.doc-item {
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}

.doc-title {
  font-size: 13px;
  font-weight: 600;
}

.doc-meta {
  font-size: 10px;
  color: var(--text-muted);
  margin: 4px 0;
}

.chat-scroll {
  flex: 1;
  padding: 16px;
}

.msg {
  margin-bottom: 16px;
}

.msg.user .bubble {
  margin-left: auto;
  background: rgba(61, 214, 195, 0.15);
  border-color: rgba(61, 214, 195, 0.35);
}

.bubble {
  max-width: 85%;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.5;
}

.citations {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.backend-tag {
  margin-top: 6px;
  font-size: 10px;
  color: var(--accent);
}

.cite-tag {
  cursor: help;
}

.composer {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border);
  align-items: flex-end;
}

.disclaimer {
  margin: 0;
  padding: 0 12px 8px;
  font-size: 10px;
  color: var(--text-muted);
}
</style>
