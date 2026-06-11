<script setup lang="ts">
import { computed } from "vue";
import { GREEK_META, type GreekKey } from "./greekLabels";

const props = withDefaults(
  defineProps<{
    greek: GreekKey;
    /** e.g. B / D venue prefix */
    prefix?: string;
    /** e.g. 净 */
    lead?: string;
    /** e.g. （USD）、（日） */
    suffix?: string;
    layout?: "stack" | "inline";
    showHint?: boolean;
  }>(),
  {
    layout: "stack",
    showHint: false,
  },
);

const meta = computed(() => GREEK_META[props.greek]);

const symbolLine = computed(() => {
  const chunks: string[] = [];
  if (props.lead) chunks.push(props.lead.trim());
  if (props.prefix) chunks.push(props.prefix.trim());
  chunks.push(meta.value.symbol);
  let line = chunks.join(" ");
  if (props.suffix) line += props.suffix;
  return line;
});
</script>

<template>
  <span
    class="greek-label"
    :class="layout"
    :title="showHint ? meta.hint : meta.name"
  >
    <span class="greek-sym">{{ symbolLine }}</span>
    <span class="greek-name">{{ meta.name }}</span>
    <span v-if="showHint && layout === 'stack'" class="greek-hint">{{ meta.hint }}</span>
  </span>
</template>

<style scoped>
.greek-label.stack {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.15;
  gap: 1px;
}
.greek-label.inline {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  line-height: 1.2;
}
.greek-sym {
  font-weight: 600;
  white-space: nowrap;
}
.greek-name {
  font-size: 10px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.greek-hint {
  font-size: 10px;
  color: var(--el-text-color-placeholder);
  white-space: nowrap;
}
</style>
