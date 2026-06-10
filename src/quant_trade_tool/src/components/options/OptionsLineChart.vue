<script setup lang="ts">
import { computed } from "vue";

export interface LinePoint {
  label: string;
  value: number;
}

const props = withDefaults(
  defineProps<{
    points: LinePoint[];
    height?: number;
    yFormat?: (v: number) => string;
    color?: string;
    threshold?: number | null;
    thresholdLabel?: string;
  }>(),
  {
    height: 200,
    color: "var(--el-color-primary)",
    threshold: null,
    thresholdLabel: "告警",
  },
);

const layout = computed(() => {
  const pts = props.points?.filter((p) => Number.isFinite(p.value)) ?? [];
  if (pts.length < 2) return null;

  const width = 720;
  const height = props.height;
  const padL = 52;
  const padR = 12;
  const padT = 16;
  const padB = 36;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const values = pts.map((p) => p.value);
  let yMin = Math.min(...values);
  let yMax = Math.max(...values);
  if (props.threshold != null) {
    yMin = Math.min(yMin, props.threshold);
    yMax = Math.max(yMax, props.threshold);
  }
  const span = yMax - yMin || Math.max(Math.abs(yMax), 1) * 0.02;
  yMin -= span * 0.08;
  yMax += span * 0.08;

  const toY = (v: number) => padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  const toX = (i: number) => padL + (i / (pts.length - 1)) * plotW;

  const coords = pts.map((p, i) => ({ ...p, x: toX(i), y: toY(p.value) }));
  const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");

  const fmt = props.yFormat ?? ((v: number) => v.toFixed(2));
  const yTicks = 4;
  const yLabels = Array.from({ length: yTicks + 1 }, (_, i) => {
    const v = yMin + ((yMax - yMin) * (yTicks - i)) / yTicks;
    return { v, y: toY(v), label: fmt(v) };
  });

  const thresholdY =
    props.threshold != null && props.threshold >= yMin && props.threshold <= yMax
      ? toY(props.threshold)
      : null;

  const xLabels = coords.filter((_, i) => i === 0 || i === coords.length - 1 || i % Math.ceil(coords.length / 5) === 0);

  return { width, height, padL, padT, plotW, plotH, coords, linePath, yLabels, thresholdY, xLabels, fmt };
});
</script>

<template>
  <div v-if="layout" class="chart-wrap">
    <svg :viewBox="`0 0 ${layout.width} ${layout.height}`" class="chart-svg" preserveAspectRatio="xMidYMid meet">
      <line
        v-for="(t, i) in layout.yLabels"
        :key="'g' + i"
        :x1="layout.padL"
        :x2="layout.padL + layout.plotW"
        :y1="t.y"
        :y2="t.y"
        class="grid-line"
      />
      <text
        v-for="(t, i) in layout.yLabels"
        :key="'y' + i"
        :x="layout.padL - 6"
        :y="t.y + 4"
        class="axis-label"
        text-anchor="end"
      >
        {{ t.label }}
      </text>
      <line
        v-if="layout.thresholdY != null"
        :x1="layout.padL"
        :x2="layout.padL + layout.plotW"
        :y1="layout.thresholdY"
        :y2="layout.thresholdY"
        class="threshold-line"
      />
      <path :d="layout.linePath" fill="none" :stroke="color" stroke-width="2" />
      <circle
        v-for="(c, i) in layout.coords"
        :key="'c' + i"
        :cx="c.x"
        :cy="c.y"
        r="3"
        :fill="color"
      />
      <text
        v-for="(c, i) in layout.xLabels"
        :key="'x' + i"
        :x="c.x"
        :y="layout.height - 8"
        class="axis-label"
        text-anchor="middle"
      >
        {{ c.label.length > 10 ? c.label.slice(5, 16) : c.label }}
      </text>
    </svg>
    <p v-if="threshold != null" class="legend muted small">
      <span class="thresh-dot" /> {{ thresholdLabel }} {{ yFormat ? yFormat(threshold) : threshold }}
    </p>
  </div>
  <p v-else class="muted small">数据点不足，无法绘图</p>
</template>

<style scoped>
.chart-wrap {
  width: 100%;
  overflow: hidden;
}
.chart-svg {
  width: 100%;
  height: auto;
  display: block;
}
.grid-line {
  stroke: var(--el-border-color-lighter);
  stroke-width: 1;
}
.axis-label {
  font-size: 10px;
  fill: var(--text-muted);
}
.threshold-line {
  stroke: var(--el-color-warning);
  stroke-width: 1.5;
  stroke-dasharray: 4 3;
}
.legend {
  margin: 4px 0 0;
}
.thresh-dot {
  display: inline-block;
  width: 12px;
  height: 0;
  border-top: 2px dashed var(--el-color-warning);
  vertical-align: middle;
  margin-right: 4px;
}
.muted {
  color: var(--text-muted);
}
.small {
  font-size: 11px;
}
</style>
