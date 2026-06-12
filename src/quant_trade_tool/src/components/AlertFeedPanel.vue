<script setup lang="ts">
import { computed } from "vue";

export type AlertFeedRow = {
  ts?: string;
  job_id?: string;
  rule?: string;
  message?: string;
  rule_label?: string;
  rule_emoji?: string;
  severity?: string;
  message_preview?: string;
  message_lines?: string[];
};

const props = withDefaults(
  defineProps<{
    items: AlertFeedRow[];
    maxHeight?: number;
    emptyText?: string;
  }>(),
  { maxHeight: 320, emptyText: "暂无告警记录" },
);

const RULE_FALLBACK: Record<string, { label: string; emoji: string; severity: string }> = {
  cycle_error: { label: "调度失败", emoji: "🚨", severity: "critical" },
  worker_crash: { label: "线程异常", emoji: "💥", severity: "critical" },
  consecutive_failures: { label: "连续失败", emoji: "🔁", severity: "critical" },
  stale_running: { label: "任务卡住", emoji: "⏳", severity: "warning" },
  cycle_complete: { label: "分析完成", emoji: "📊", severity: "success" },
  custom_signal: { label: "自定义信号", emoji: "🎯", severity: "warning" },
  var_breach: { label: "VaR 超限", emoji: "⚠️", severity: "warning" },
};

const rows = computed(() =>
  props.items.map((item) => {
    const rule = item.rule || "";
    const fb = RULE_FALLBACK[rule] || { label: rule || "告警", emoji: "🔔", severity: "warning" };
    const msg = item.message || "";
    const lines = item.message_lines?.length
      ? item.message_lines
      : msg.split("\n").filter((l) => l.trim());
    return {
      ...item,
      rule_label: item.rule_label || fb.label,
      rule_emoji: item.rule_emoji || fb.emoji,
      severity: item.severity || fb.severity,
      preview: item.message_preview || lines[0] || msg.slice(0, 120),
      lines: lines.slice(0, 6),
    };
  }),
);

function formatTs(raw?: string) {
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw.slice(0, 16);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${m}-${day} ${hh}:${mm}`;
}
</script>

<template>
  <div v-if="!rows.length" class="feed-empty">{{ emptyText }}</div>
  <div v-else class="alert-feed" :style="{ maxHeight: `${maxHeight}px` }">
    <article
      v-for="(row, idx) in rows"
      :key="`${row.ts}-${row.rule}-${idx}`"
      class="alert-item"
      :class="`sev-${row.severity}`"
    >
      <header class="alert-head">
        <span class="alert-emoji">{{ row.rule_emoji }}</span>
        <div class="alert-meta">
          <div class="alert-title">
            <strong>{{ row.rule_label }}</strong>
            <el-tag v-if="row.job_id" size="small" type="info" effect="plain">{{ row.job_id }}</el-tag>
          </div>
          <time class="alert-time">{{ formatTs(row.ts) }}</time>
        </div>
      </header>
      <p class="alert-preview">{{ row.preview }}</p>
      <ul v-if="row.lines.length > 1" class="alert-lines">
        <li v-for="(line, i) in row.lines.slice(1)" :key="i">{{ line }}</li>
      </ul>
    </article>
  </div>
</template>

<style scoped>
.alert-feed {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
}

.feed-empty {
  color: var(--text-muted);
  font-size: 13px;
  padding: 12px 0;
  text-align: center;
}

.alert-item {
  border: 1px solid var(--border);
  border-left-width: 4px;
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--bg-elevated);
}

.alert-item.sev-critical {
  border-left-color: var(--el-color-danger);
}
.alert-item.sev-warning {
  border-left-color: var(--el-color-warning);
}
.alert-item.sev-success {
  border-left-color: var(--el-color-success);
}
.alert-item.sev-info {
  border-left-color: var(--el-color-info);
}

.alert-head {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.alert-emoji {
  font-size: 1.25rem;
  line-height: 1;
}

.alert-meta {
  flex: 1;
  min-width: 0;
}

.alert-title {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.alert-time {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.alert-preview {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.45;
  color: var(--text);
}

.alert-lines {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}
</style>
