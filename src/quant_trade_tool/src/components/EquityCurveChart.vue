<script setup lang="ts">
import { computed, ref } from "vue";

export interface EquityPoint {
  time: string;
  value: number;
}

const props = withDefaults(
  defineProps<{
    data: EquityPoint[];
    capitalBase?: number;
    height?: number;
  }>(),
  { height: 240 },
);

const hoverIndex = ref<number | null>(null);
const svgRef = ref<SVGSVGElement | null>(null);

const layout = computed(() => {
  const points = props.data?.filter((p) => Number.isFinite(p.value)) ?? [];
  if (points.length < 2) return null;

  const width = 860;
  const height = props.height;
  const padL = 64;
  const padR = 16;
  const padT = 20;
  const padB = 32;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const values = points.map((p) => p.value);
  const base = props.capitalBase;
  let yMin = Math.min(...values);
  let yMax = Math.max(...values);
  if (base != null) {
    yMin = Math.min(yMin, base);
    yMax = Math.max(yMax, base);
  }
  const span = yMax - yMin || Math.max(Math.abs(yMax), 1) * 0.02;
  yMin -= span * 0.06;
  yMax += span * 0.06;

  const toY = (v: number) => padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  const toX = (i: number) => padL + (i / (points.length - 1)) * plotW;

  const coords = points.map((p, i) => ({
    ...p,
    x: toX(i),
    y: toY(p.value),
  }));

  const linePath = coords
    .map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(2)},${c.y.toFixed(2)}`)
    .join(" ");
  const areaPath = `${linePath} L${coords[coords.length - 1].x.toFixed(2)},${(padT + plotH).toFixed(2)} L${coords[0].x.toFixed(2)},${(padT + plotH).toFixed(2)} Z`;

  const yTicks = 4;
  const yLabels = Array.from({ length: yTicks + 1 }, (_, i) => {
    const v = yMin + ((yMax - yMin) * (yTicks - i)) / yTicks;
    return { v, y: toY(v) };
  });

  const baseY = base != null ? toY(base) : null;
  const finalReturn =
    base != null && base > 0 ? (values[values.length - 1] - base) / base : null;
  const isUp = finalReturn != null ? finalReturn >= 0 : values[values.length - 1] >= values[0];

  return {
    width,
    height,
    padL,
    padT,
    plotW,
    plotH,
    coords,
    linePath,
    areaPath,
    yLabels,
    baseY,
    isUp,
    firstLabel: formatAxisTime(points[0].time),
    lastLabel: formatAxisTime(points[points.length - 1].time),
  };
});

const hoverPoint = computed(() => {
  if (hoverIndex.value == null || !layout.value) return null;
  return layout.value.coords[hoverIndex.value] ?? null;
});

function formatAxisTime(raw: string) {
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw.slice(0, 16);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${m}-${day} ${hh}:${mm}`;
}

function formatMoney(v: number) {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (Math.abs(v) >= 10_000) return `${(v / 1_000).toFixed(1)}k`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function onMouseMove(e: MouseEvent) {
  const svg = svgRef.value;
  const chart = layout.value;
  if (!svg || !chart) return;
  const rect = svg.getBoundingClientRect();
  const scaleX = chart.width / rect.width;
  const x = (e.clientX - rect.left) * scaleX;
  const rel = (x - chart.padL) / chart.plotW;
  if (rel < 0 || rel > 1) {
    hoverIndex.value = null;
    return;
  }
  hoverIndex.value = Math.round(rel * (chart.coords.length - 1));
}

function onMouseLeave() {
  hoverIndex.value = null;
}
</script>

<template>
  <div v-if="layout" class="equity-chart">
    <svg
      ref="svgRef"
      class="equity-svg"
      :viewBox="`0 0 ${layout.width} ${layout.height}`"
      preserveAspectRatio="xMidYMid meet"
      @mousemove="onMouseMove"
      @mouseleave="onMouseLeave"
    >
      <defs>
        <linearGradient id="equityAreaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="layout.isUp ? 'var(--equity-up)' : 'var(--equity-down)'" stop-opacity="0.28" />
          <stop offset="100%" stop-color="var(--equity-area-end)" stop-opacity="0.02" />
        </linearGradient>
      </defs>

      <g class="grid">
        <line
          v-for="(tick, i) in layout.yLabels"
          :key="i"
          :x1="layout.padL"
          :y1="tick.y"
          :x2="layout.padL + layout.plotW"
          :y2="tick.y"
          class="grid-line"
        />
      </g>

      <g class="y-labels">
        <text
          v-for="(tick, i) in layout.yLabels"
          :key="`y-${i}`"
          :x="layout.padL - 8"
          :y="tick.y + 4"
          text-anchor="end"
          class="axis-label"
        >
          {{ formatMoney(tick.v) }}
        </text>
      </g>

      <line
        v-if="layout.baseY != null"
        :x1="layout.padL"
        :y1="layout.baseY"
        :x2="layout.padL + layout.plotW"
        :y2="layout.baseY"
        class="baseline"
      />

      <path :d="layout.areaPath" class="equity-area" fill="url(#equityAreaGrad)" />
      <path
        :d="layout.linePath"
        class="equity-line"
        :class="{ up: layout.isUp, down: !layout.isUp }"
        fill="none"
      />

      <g v-if="hoverPoint" class="hover">
        <line
          :x1="hoverPoint.x"
          :y1="layout.padT"
          :x2="hoverPoint.x"
          :y2="layout.padT + layout.plotH"
          class="hover-line"
        />
        <circle :cx="hoverPoint.x" :cy="hoverPoint.y" r="4.5" class="hover-dot" />
      </g>

      <text :x="layout.padL" :y="layout.height - 8" class="axis-label">{{ layout.firstLabel }}</text>
      <text
        :x="layout.padL + layout.plotW"
        :y="layout.height - 8"
        text-anchor="end"
        class="axis-label"
      >
        {{ layout.lastLabel }}
      </text>
    </svg>

    <div v-if="hoverPoint" class="tooltip">
      <span class="tooltip-time">{{ formatAxisTime(hoverPoint.time) }}</span>
      <span class="tooltip-value">{{ formatMoney(hoverPoint.value) }}</span>
      <span
        v-if="capitalBase != null && capitalBase > 0"
        class="tooltip-ret"
        :class="hoverPoint.value >= capitalBase ? 'up' : 'down'"
      >
        {{ ((hoverPoint.value - capitalBase) / capitalBase * 100).toFixed(2) }}%
      </span>
    </div>
  </div>
  <p v-else class="muted small">净值点不足，无法绘制曲线</p>
</template>

<style scoped>
.equity-chart {
  position: relative;
  width: 100%;
  margin-top: 12px;
  --equity-up: var(--el-color-success);
  --equity-down: var(--el-color-danger);
  --equity-area-end: var(--el-bg-color);
}

.equity-svg {
  display: block;
  width: 100%;
  height: auto;
  cursor: crosshair;
  user-select: none;
}

.grid-line {
  stroke: var(--el-border-color-lighter);
  stroke-width: 1;
  stroke-dasharray: 4 4;
}

.axis-label {
  fill: var(--text-muted);
  font-size: 11px;
}

.baseline {
  stroke: var(--el-color-info-light-5);
  stroke-width: 1;
  stroke-dasharray: 6 4;
}

.equity-line {
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.equity-line.up {
  stroke: var(--equity-up);
}

.equity-line.down {
  stroke: var(--equity-down);
}

.hover-line {
  stroke: var(--el-color-primary-light-3);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}

.hover-dot {
  fill: var(--el-bg-color);
  stroke: var(--el-color-primary);
  stroke-width: 2;
}

.tooltip {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  font-size: 12px;
  pointer-events: none;
  box-shadow: var(--el-box-shadow-light);
}

.tooltip-time {
  color: var(--text-muted);
}

.tooltip-value {
  font-weight: 600;
  font-size: 14px;
}

.tooltip-ret.up {
  color: var(--el-color-success);
}

.tooltip-ret.down {
  color: var(--el-color-danger);
}

.muted {
  color: var(--text-muted);
}

.small {
  font-size: 12px;
}
</style>
