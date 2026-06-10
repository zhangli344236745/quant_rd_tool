<script setup lang="ts">
import { computed } from "vue";

export interface VenueSeries {
  name: string;
  color: string;
  points: { label: string; value: number }[];
}

const props = defineProps<{
  series: VenueSeries[];
  height?: number;
}>();

const layout = computed(() => {
  const active = props.series?.filter((s) => s.points?.length >= 2) ?? [];
  if (!active.length) return null;

  const width = 720;
  const height = props.height ?? 200;
  const padL = 52;
  const padR = 12;
  const padT = 16;
  const padB = 36;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const maxLen = Math.max(...active.map((s) => s.points.length));
  const allVals = active.flatMap((s) => s.points.map((p) => p.value));
  let yMin = Math.min(...allVals);
  let yMax = Math.max(...allVals);
  const span = yMax - yMin || 1;
  yMin -= span * 0.08;
  yMax += span * 0.08;

  const toY = (v: number) => padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  const toX = (i: number, n: number) => padL + (i / Math.max(n - 1, 1)) * plotW;

  const drawn = active.map((s) => {
    const coords = s.points.map((p, i) => ({
      ...p,
      x: toX(i, s.points.length),
      y: toY(p.value),
    }));
    const path = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
    return { ...s, coords, path };
  });

  return { width, height, padL, padT, plotW, plotH, drawn, yMin, yMax, toY };
});
</script>

<template>
  <div v-if="layout" class="chart-wrap">
    <svg :viewBox="`0 0 ${layout.width} ${layout.height}`" class="chart-svg" preserveAspectRatio="xMidYMid meet">
      <path
        v-for="(s, i) in layout.drawn"
        :key="i"
        :d="s.path"
        fill="none"
        :stroke="s.color"
        stroke-width="2"
      />
      <template v-for="(s, si) in layout.drawn" :key="'pts' + si">
        <circle
          v-for="(c, ci) in s.coords"
          :key="`${si}-${ci}`"
          :cx="c.x"
          :cy="c.y"
          r="3"
          :fill="s.color"
        />
      </template>
    </svg>
    <p class="legend small muted">
      <span v-for="(s, i) in series" :key="i" class="leg-item">
        <span class="dot" :style="{ background: s.color }" /> {{ s.name }}
      </span>
    </p>
  </div>
  <p v-else class="muted small">期限结构对比数据不足</p>
</template>

<style scoped>
.chart-wrap {
  width: 100%;
}
.chart-svg {
  width: 100%;
  height: auto;
}
.legend {
  display: flex;
  gap: 16px;
  margin: 6px 0 0;
}
.leg-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.muted {
  color: var(--text-muted);
}
.small {
  font-size: 11px;
}
</style>
