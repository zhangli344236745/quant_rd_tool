<script setup lang="ts">
import { computed } from "vue";

export interface SkewPoint {
  strike: number;
  mark_iv: number;
  moneyness_pct?: number;
}

const props = defineProps<{
  points: SkewPoint[];
  spot?: number;
  height?: number;
}>();

const layout = computed(() => {
  const pts = props.points?.filter((p) => p.mark_iv > 0) ?? [];
  if (pts.length < 2) return null;

  const width = 720;
  const height = props.height ?? 200;
  const padL = 48;
  const padR = 12;
  const padT = 16;
  const padB = 36;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const strikes = pts.map((p) => p.strike);
  const ivs = pts.map((p) => p.mark_iv * 100);
  const kMin = Math.min(...strikes);
  const kMax = Math.max(...strikes);
  const ivMin = Math.min(...ivs);
  const ivMax = Math.max(...ivs);
  const kSpan = kMax - kMin || 1;
  const ivSpan = ivMax - ivMin || 1;

  const toX = (k: number) => padL + ((k - kMin) / kSpan) * plotW;
  const toY = (iv: number) => padT + plotH - ((iv - ivMin + ivSpan * 0.05) / (ivSpan * 1.1)) * plotH;

  const coords = pts.map((p) => ({
    ...p,
    x: toX(p.strike),
    y: toY(p.mark_iv * 100),
  }));
  const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");

  let spotX: number | null = null;
  if (props.spot != null && props.spot >= kMin && props.spot <= kMax) {
    spotX = toX(props.spot);
  }

  return { width, height, padL, padT, plotW, plotH, coords, linePath, spotX, ivMin, ivMax };
});
</script>

<template>
  <div v-if="layout" class="chart-wrap">
    <svg :viewBox="`0 0 ${layout.width} ${layout.height}`" class="chart-svg" preserveAspectRatio="xMidYMid meet">
      <line
        v-if="layout.spotX != null"
        :x1="layout.spotX"
        :x2="layout.spotX"
        :y1="layout.padT"
        :y2="layout.padT + layout.plotH"
        class="spot-line"
      />
      <path :d="layout.linePath" fill="none" stroke="var(--el-color-success)" stroke-width="2" />
      <circle v-for="(c, i) in layout.coords" :key="i" :cx="c.x" :cy="c.y" r="3" fill="var(--el-color-success)" />
    </svg>
    <p class="muted small">纵轴：Mark IV % · 竖线：现货价</p>
  </div>
  <p v-else class="muted small">偏斜数据不足</p>
</template>

<style scoped>
.chart-wrap {
  width: 100%;
}
.chart-svg {
  width: 100%;
  height: auto;
}
.spot-line {
  stroke: var(--el-color-info);
  stroke-dasharray: 4 3;
  stroke-width: 1;
}
.muted {
  color: var(--text-muted);
  font-size: 11px;
  margin: 4px 0 0;
}
</style>
