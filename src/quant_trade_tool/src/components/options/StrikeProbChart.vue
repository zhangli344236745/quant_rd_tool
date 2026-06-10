<script setup lang="ts">
import { computed } from "vue";

export interface StrikeProbBar {
  strike: number;
  model: number | null | undefined;
  implied: number | null | undefined;
}

const props = defineProps<{
  rows: StrikeProbBar[];
  field?: "call" | "put";
  height?: number;
}>();

const layout = computed(() => {
  const rows = props.rows?.filter((r) => r.model != null || r.implied != null) ?? [];
  if (!rows.length) return null;

  const width = 720;
  const height = props.height ?? 220;
  const padL = 48;
  const padR = 12;
  const padT = 16;
  const padB = 40;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const barGroupW = plotW / rows.length;
  const barW = Math.min(14, barGroupW * 0.28);

  const maxV = Math.max(
    0.01,
    ...rows.flatMap((r) => [r.model ?? 0, r.implied ?? 0]),
  );

  const toY = (v: number) => padT + plotH - (v / maxV) * plotH;

  const bars = rows.map((r, i) => {
    const cx = padL + i * barGroupW + barGroupW / 2;
    return {
      strike: r.strike,
      modelY: r.model != null ? toY(r.model) : null,
      impliedY: r.implied != null ? toY(r.implied) : null,
      modelH: r.model != null ? padT + plotH - toY(r.model) : 0,
      impliedH: r.implied != null ? padT + plotH - toY(r.implied) : 0,
      cx,
      labelX: cx,
    };
  });

  return { width, height, padT, plotH, padL, plotW, bars, barW, maxV };
});
</script>

<template>
  <div v-if="layout" class="chart-wrap">
    <svg :viewBox="`0 0 ${layout.width} ${layout.height}`" class="chart-svg" preserveAspectRatio="xMidYMid meet">
      <rect
        v-for="(b, i) in layout.bars"
        :key="'m' + i"
        v-show="b.modelY != null"
        :x="b.cx - layout.barW - 2"
        :y="b.modelY!"
        :width="layout.barW"
        :height="b.modelH"
        class="bar-model"
      />
      <rect
        v-for="(b, i) in layout.bars"
        :key="'i' + i"
        v-show="b.impliedY != null"
        :x="b.cx + 2"
        :y="b.impliedY!"
        :width="layout.barW"
        :height="b.impliedH"
        class="bar-implied"
      />
      <text
        v-for="(b, i) in layout.bars"
        :key="'l' + i"
        :x="b.labelX"
        :y="layout.height - 8"
        class="axis-label"
        text-anchor="middle"
      >
        {{ b.strike >= 1000 ? (b.strike / 1000).toFixed(0) + "k" : b.strike }}
      </text>
    </svg>
    <p class="legend small muted">
      <span class="dot model" /> 模型
      <span class="dot implied" /> 隐含
    </p>
  </div>
  <p v-else class="muted small">无概率数据</p>
</template>

<style scoped>
.chart-wrap {
  width: 100%;
}
.chart-svg {
  width: 100%;
  height: auto;
}
.bar-model {
  fill: var(--el-color-primary);
  opacity: 0.85;
}
.bar-implied {
  fill: var(--el-color-warning);
  opacity: 0.85;
}
.axis-label {
  font-size: 9px;
  fill: var(--text-muted);
}
.legend {
  margin: 6px 0 0;
  display: flex;
  gap: 16px;
  align-items: center;
}
.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
  vertical-align: middle;
}
.dot.model {
  background: var(--el-color-primary);
}
.dot.implied {
  background: var(--el-color-warning);
}
.muted {
  color: var(--text-muted);
}
.small {
  font-size: 11px;
}
</style>
