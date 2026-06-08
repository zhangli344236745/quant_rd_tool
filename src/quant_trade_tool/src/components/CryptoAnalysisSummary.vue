<script setup lang="ts">
import { computed } from "vue";

export interface CryptoUiSummary {
  symbol?: string;
  pair?: string;
  timeframe?: string;
  period?: { start?: string; end?: string; bars?: number };
  headline?: string;
  summary?: string;
  stance?: string;
  action?: string;
  action_label?: string;
  advice?: string;
  confidence?: number;
  agreement?: string;
  technical_stance?: string;
  ml_stance?: string;
  price_lines?: string[];
  technical_lines?: string[];
  observations?: string[];
  risks?: string[];
  brief_sections?: Array<{
    title: string;
    paragraphs?: string[];
    bullets?: string[];
    scenarios?: Array<{ role: string; text: string }>;
    upgrades?: Array<{ condition: string; bias: string }>;
  }>;
  disclaimer?: string;
}

const props = defineProps<{
  summary?: CryptoUiSummary | null;
}>();

const stanceTagType = computed(() => {
  const s = props.summary?.stance;
  if (s === "看涨") return "success";
  if (s === "看跌") return "danger";
  return "info";
});

const actionTagType = computed(() => {
  const a = props.summary?.action;
  if (a === "buy") return "success";
  if (a === "sell") return "danger";
  return "info";
});

const confidenceText = computed(() => {
  const c = props.summary?.confidence;
  return typeof c === "number" ? `${(c * 100).toFixed(0)}%` : "—";
});

const periodText = computed(() => {
  const p = props.summary?.period;
  if (!p?.start || !p?.end) return "";
  const tf = props.summary?.timeframe || "1d";
  const unit = tf === "1d" ? "根日线" : "根 K 线";
  return `${p.start} ~ ${p.end}（${p.bars ?? "—"} ${unit}）`;
});

function stripMd(text: string) {
  return text.replace(/\*\*/g, "");
}
</script>

<template>
  <div v-if="summary" class="crypto-summary">
    <div class="hero">
      <el-tag :type="stanceTagType" size="large" effect="dark">{{ summary.stance || "—" }}</el-tag>
      <el-tag :type="actionTagType" size="large" class="ml">
        {{ summary.action_label || summary.action || "—" }}
      </el-tag>
      <span class="meta">置信度 {{ confidenceText }}</span>
      <span v-if="summary.agreement" class="meta">· {{ summary.agreement }}</span>
    </div>

    <p v-if="summary.headline" class="headline">{{ summary.headline }}</p>
    <p v-else-if="summary.summary" class="headline">{{ summary.summary }}</p>

    <p v-if="periodText" class="period muted">{{ summary.pair || summary.symbol }} · {{ summary.timeframe }} · {{ periodText }}</p>

    <el-alert
      v-if="summary.advice"
      :title="summary.advice"
      type="info"
      :closable="false"
      show-icon
      class="advice"
    />

    <div class="grid">
      <div v-if="summary.price_lines?.length" class="block">
        <h4>价格概况</h4>
        <ul>
          <li v-for="(line, i) in summary.price_lines" :key="'p' + i">{{ line }}</li>
        </ul>
      </div>
      <div v-if="summary.technical_lines?.length" class="block">
        <h4>技术指标（白话）</h4>
        <ul>
          <li v-for="(line, i) in summary.technical_lines" :key="'t' + i">{{ line }}</li>
        </ul>
      </div>
    </div>

    <p class="dim-line muted">
      技术面 <strong>{{ summary.technical_stance || "—" }}</strong>
      · 机器学习 <strong>{{ summary.ml_stance || "—" }}</strong>
    </p>

    <div v-if="summary.observations?.length" class="block">
      <h4>关键观察</h4>
      <ul>
        <li v-for="(o, i) in summary.observations.slice(0, 8)" :key="'o' + i">{{ o }}</li>
      </ul>
    </div>

    <el-collapse v-if="summary.brief_sections?.length" class="brief-collapse">
      <el-collapse-item
        v-for="(sec, idx) in summary.brief_sections"
        :key="idx"
        :title="sec.title"
        :name="String(idx)"
      >
        <p v-for="(p, pi) in sec.paragraphs || []" :key="'pp' + pi" class="para">{{ stripMd(p) }}</p>
        <ul v-if="sec.bullets?.length">
          <li v-for="(b, bi) in sec.bullets" :key="'bb' + bi">{{ stripMd(b) }}</li>
        </ul>
        <ul v-if="sec.scenarios?.length" class="scenarios">
          <li v-for="(sc, si) in sec.scenarios" :key="'sc' + si">
            <strong>{{ sc.role }}</strong>：{{ sc.text }}
          </li>
        </ul>
        <ul v-if="sec.upgrades?.length">
          <li v-for="(up, ui) in sec.upgrades" :key="'up' + ui">
            若 {{ up.condition }} → {{ up.bias }}
          </li>
        </ul>
      </el-collapse-item>
    </el-collapse>

    <div v-if="summary.risks?.length" class="block risks">
      <h4>风险提示</h4>
      <ul>
        <li v-for="(r, i) in summary.risks" :key="'r' + i">{{ r }}</li>
      </ul>
    </div>

    <p v-if="summary.disclaimer" class="disclaimer muted">{{ summary.disclaimer }}</p>
  </div>
</template>

<style scoped>
.crypto-summary {
  font-size: 14px;
  line-height: 1.6;
}

.hero {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.ml {
  margin-left: 0;
}

.meta {
  color: var(--text-muted);
  font-size: 13px;
}

.headline {
  margin: 0 0 10px;
  font-size: 15px;
  font-weight: 500;
  line-height: 1.55;
}

.period {
  margin: 0 0 12px;
  font-size: 12px;
}

.advice {
  margin-bottom: 14px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 12px;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
}

.block h4 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.block ul {
  margin: 0;
  padding-left: 18px;
  color: var(--text-muted);
  font-size: 13px;
}

.block li {
  margin-bottom: 4px;
}

.dim-line {
  margin: 0 0 12px;
  font-size: 13px;
}

.brief-collapse {
  margin: 12px 0;
  border: none;
}

.para {
  margin: 0 0 8px;
  color: var(--text-muted);
  font-size: 13px;
}

.scenarios li {
  margin-bottom: 6px;
}

.risks ul {
  color: var(--el-color-warning);
}

.disclaimer {
  margin: 12px 0 0;
  font-size: 12px;
}

.muted {
  color: var(--text-muted);
}
</style>
