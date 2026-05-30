<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  signal?: Record<string, unknown>;
}>();

const action = computed(() => String(props.signal?.action || "hold"));
const stance = computed(() => String(props.signal?.stance || "—"));
const confidence = computed(() => {
  const c = props.signal?.confidence;
  return typeof c === "number" ? `${(c * 100).toFixed(0)}%` : "—";
});
const score = computed(() => props.signal?.score ?? "—");

const tagType = computed(() => {
  if (action.value === "buy") return "success";
  if (action.value === "sell") return "danger";
  return "info";
});
</script>

<template>
  <div v-if="signal" class="signal-row">
    <el-tag :type="tagType" size="large" class="action-tag">{{ action.toUpperCase() }}</el-tag>
    <div class="meta">
      <span>{{ stance }}</span>
      <span class="dot">·</span>
      <span>置信度 {{ confidence }}</span>
      <span class="dot">·</span>
      <span>得分 {{ score }}</span>
    </div>
    <ul v-if="Array.isArray(signal.reasons)" class="reasons">
      <li v-for="(r, i) in (signal.reasons as string[]).slice(0, 6)" :key="i">{{ r }}</li>
    </ul>
  </div>
</template>

<style scoped>
.signal-row {
  padding: 12px 0;
}

.action-tag {
  font-weight: 600;
  letter-spacing: 0.06em;
}

.meta {
  margin-top: 10px;
  color: var(--text-muted);
  font-size: 0.9rem;
}

.dot {
  margin: 0 6px;
}

.reasons {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--text-muted);
  font-size: 0.85rem;
  line-height: 1.6;
}
</style>
