<script setup lang="ts">
import { reactive, ref } from "vue";
import { cryptoApi, type CryptoNewsDigest, type SymbolVarBreach, type SymbolVarReport } from "@/api/crypto";
import { jobsApi } from "@/api/jobs";
import { useJobSubmit } from "@/composables/useJobSubmit";
import CryptoAnalysisSummary, {
  type CryptoUiSummary,
} from "@/components/CryptoAnalysisSummary.vue";
import ResultPanel from "@/components/ResultPanel.vue";
import SignalSummary from "@/components/SignalSummary.vue";

const symbolVar = ref<SymbolVarReport | null>(null);
const symbolVarBreach = ref<SymbolVarBreach | null>(null);
const symbolVarError = ref("");

const form = reactive({
  symbol: "BTC",
  timeframe: "5m",
  limit: 800,
  data_dir: "data/crypto",
  with_ml: true,
  ml_algorithm: "both",
  with_options_vol: true,
});

const { submit, polling } = useJobSubmit();
const result = ref<Record<string, unknown> | null>(null);
const uiSummary = ref<CryptoUiSummary | null>(null);
const showRaw = ref(false);
const error = ref("");

async function loadSymbolVarSummary(symbol: string) {
  symbolVar.value = null;
  symbolVarBreach.value = null;
  symbolVarError.value = "";
  try {
    const [symRes, breachRes] = await Promise.all([
      cryptoApi.varSymbol({
        symbol,
        notional_usdt: 10000,
        confidence: "0.99",
        horizon_bars: 1,
        lookback_bars: 0,
        timeframe: "4h",
      }),
      cryptoApi.varSymbolBreach({
        symbol,
        confidence: 0.99,
        timeframe: "4h",
        horizon_bars: 1,
        lookback_bars: 0,
        notional_usdt: 10000,
      }),
    ]);
    symbolVar.value = symRes.data;
    symbolVarBreach.value = breachRes.data;
  } catch (e) {
    symbolVarError.value = String(e);
  }
}

async function run(wait: boolean) {
  error.value = "";
  result.value = null;
  uiSummary.value = null;
  showRaw.value = false;
  symbolVar.value = null;
  symbolVarError.value = "";
  try {
    await submit(() => jobsApi.cryptoAnalyze({ ...form }), {
      wait,
      onDone: async (r) => {
        uiSummary.value = (r.ui_summary as CryptoUiSummary) || null;
        result.value = { ...r };
        await loadSymbolVarSummary(form.symbol);
      },
    });
  } catch (e) {
    error.value = String(e);
  }
}

const var99Usdt = () => symbolVar.value?.metrics?.["0.99"]?.var_usdt;

const combined = () =>
  (result.value?.combined_signal as Record<string, unknown>) || undefined;

const optionsVol = () =>
  (result.value?.options_vol as Record<string, unknown>) || undefined;

const newsDigest = () =>
  (result.value?.news_digest as CryptoNewsDigest) || undefined;

function newsImpactType(impact: string) {
  if (impact === "bullish") return "success";
  if (impact === "bearish") return "danger";
  if (impact === "mixed") return "warning";
  return "info";
}

const newsStanceLabel: Record<string, string> = {
  bullish: "偏多",
  bearish: "偏空",
  neutral: "中性",
  mixed: "分化",
};

function optAlertType(level: string) {
  if (level === "hot") return "danger";
  if (level === "elevated") return "warning";
  return "info";
}
</script>

<template>
  <div>
    <h1 class="page-title">Crypto 行情分析</h1>
    <p class="page-desc">
      技术面 + ML + Binance 期权 IV 联合研判；默认后台任务，可在任务中心查看。
    </p>

    <el-row :gutter="20">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <el-form label-width="100px" @submit.prevent="run(true)">
            <el-form-item label="标的">
              <el-select v-model="form.symbol" style="width: 100%">
                <el-option label="BTC" value="BTC" />
                <el-option label="ETH" value="ETH" />
              </el-select>
            </el-form-item>
            <el-form-item label="周期">
              <el-select v-model="form.timeframe">
                <el-option label="5m" value="5m" />
                <el-option label="1d" value="1d" />
              </el-select>
            </el-form-item>
            <el-form-item label="K 线数量">
              <el-input-number v-model="form.limit" :min="100" :max="2000" />
            </el-form-item>
            <el-form-item label="ML">
              <el-switch v-model="form.with_ml" />
            </el-form-item>
            <el-form-item label="期权 IV">
              <el-switch v-model="form.with_options_vol" />
            </el-form-item>
            <el-form-item label="算法">
              <el-select v-model="form.ml_algorithm">
                <el-option label="both" value="both" />
                <el-option label="xgb" value="xgb" />
                <el-option label="lgb" value="lgb" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" native-type="submit" :loading="polling">分析并等待</el-button>
              <el-button :loading="polling" @click="run(false)">仅提交</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card v-if="uiSummary" shadow="never" class="panel-card">
          <template #header>分析总结（白话）</template>
          <CryptoAnalysisSummary :summary="uiSummary" />
        </el-card>
        <el-card v-else-if="combined()" shadow="never" class="panel-card">
          <template #header>综合信号</template>
          <SignalSummary :signal="combined()" />
        </el-card>
        <el-card v-if="symbolVar || symbolVarError" shadow="never" class="panel-card mt">
          <template #header>风险 VaR 摘要</template>
          <template v-if="symbolVar">
            <el-alert
              v-if="symbolVarBreach?.breached"
              type="error"
              :title="`4h 滚动 VaR 突破：实际 ${((symbolVarBreach.actual_return || 0) * 100).toFixed(2)}%`"
              show-icon
              :closable="false"
              class="mb"
            />
            <p class="cross-summary">
              4h · 99% VaR（名义 10,000 USDT）：
              <strong>{{ var99Usdt()?.toLocaleString(undefined, { maximumFractionDigits: 2 }) }} USDT</strong>
            </p>
            <router-link
              :to="{ path: '/crypto-workflow', query: { symbol: form.symbol } }"
              class="workflow-link"
            >
              Workflow 分析
            </router-link>
            <router-link
              :to="{ path: '/crypto-var', query: { symbol: form.symbol, tab: 'symbol' } }"
              class="var-link"
            >
              查看完整 VaR →
            </router-link>
          </template>
          <p v-else class="muted small">{{ symbolVarError }}</p>
        </el-card>
        <el-card
          v-if="newsDigest()?.market_stance"
          shadow="never"
          class="panel-card mt"
        >
          <template #header>舆论雷达摘要</template>
          <el-tag
            :type="newsImpactType(String(newsDigest()?.market_stance || 'neutral'))"
            size="small"
            class="mb"
          >
            {{ newsStanceLabel[String(newsDigest()?.market_stance)] || newsDigest()?.market_stance }}
          </el-tag>
          <ul v-if="(newsDigest()?.top_items || []).length" class="news-headlines">
            <li
              v-for="(item, i) in (newsDigest()?.top_items || []).slice(0, 2)"
              :key="item.id || item.link || i"
            >
              <el-tag
                :type="newsImpactType(String(item.advice?.impact || item.impact_direction || 'neutral'))"
                size="small"
                effect="plain"
                class="mr"
              >
                {{ newsStanceLabel[String(item.advice?.impact || item.impact_direction)] || "中性" }}
              </el-tag>
              {{ item.advice?.headline || item.title }}
            </li>
          </ul>
          <router-link to="/crypto-news" class="var-link">查看舆论雷达 →</router-link>
        </el-card>
        <el-card
          v-if="optionsVol()?.enabled"
          shadow="never"
          class="panel-card mt"
        >
          <template #header>期权波动 × 现货方向</template>
          <el-tag
            :type="optAlertType(String(optionsVol()?.alert_level || 'normal'))"
            size="small"
            class="mb"
          >
            {{ optionsVol()?.alert_level }}
          </el-tag>
          <p v-if="(optionsVol()?.cross_view as any)?.summary" class="cross-summary">
            {{ (optionsVol()?.cross_view as any).summary }}
          </p>
          <el-descriptions :column="2" size="small" border class="mt">
            <el-descriptions-item label="ATM IV">
              {{
                optionsVol()?.atm_iv != null
                  ? (Number(optionsVol()?.atm_iv) * 100).toFixed(1) + "%"
                  : "—"
              }}
            </el-descriptions-item>
            <el-descriptions-item label="IV 分位">
              {{ optionsVol()?.iv_percentile ?? "—" }}
            </el-descriptions-item>
            <el-descriptions-item label="24h Δ">
              {{
                optionsVol()?.iv_change_24h_pct != null
                  ? optionsVol()?.iv_change_24h_pct + "%"
                  : "—"
              }}
            </el-descriptions-item>
            <el-descriptions-item label="合约">
              {{ optionsVol()?.contract || "—" }}
            </el-descriptions-item>
            <el-descriptions-item
              v-if="optionsVol()?.peer_rank != null"
              label="横向排名"
            >
              #{{ optionsVol()?.peer_rank }}/{{ optionsVol()?.peer_count }}
            </el-descriptions-item>
            <el-descriptions-item
              v-if="optionsVol()?.hottest_peer"
              label="IV 最高"
            >
              {{ optionsVol()?.hottest_peer }}
            </el-descriptions-item>
          </el-descriptions>
          <p v-if="(optionsVol()?.advice as any)?.summary" class="muted small mt">
            {{ (optionsVol()?.advice as any).summary }}
          </p>
          <p
            v-if="((optionsVol()?.strike_ladder as any)?.purchase_summary)?.headline"
            class="purchase-headline small mt"
          >
            {{ ((optionsVol()?.strike_ladder as any).purchase_summary).headline }}
          </p>
          <p
            v-if="((optionsVol()?.strategy_pack as any)?.headline)"
            class="purchase-headline small mt"
          >
            策略：{{ (optionsVol()?.strategy_pack as any).headline }}
          </p>
          <el-descriptions
            v-if="(optionsVol()?.venue_compare as any)?.aligned?.available"
            :column="2"
            size="small"
            border
            class="mt venue-mini"
          >
            <el-descriptions-item label="跨所到期">
              {{ (optionsVol()?.venue_compare as any).aligned.expiry_date }}
            </el-descriptions-item>
            <el-descriptions-item label="B−D 价差">
              {{
                (optionsVol()?.venue_compare as any).comparison?.iv_spread_pp != null
                  ? (optionsVol()?.venue_compare as any).comparison.iv_spread_pp + "pp"
                  : "—"
              }}
            </el-descriptions-item>
            <el-descriptions-item label="偏高所">
              {{ (optionsVol()?.venue_compare as any).comparison?.richer_venue || "—" }}
            </el-descriptions-item>
            <el-descriptions-item label="Deribit IV">
              {{
                (optionsVol()?.venue_compare as any).deribit?.atm_iv != null
                  ? (Number((optionsVol()?.venue_compare as any).deribit.atm_iv) * 100).toFixed(1) + "%"
                  : "—"
              }}
            </el-descriptions-item>
          </el-descriptions>
          <p
            v-if="(optionsVol()?.venue_compare as any)?.comparison?.summary"
            class="muted small mt"
          >
            {{ (optionsVol()?.venue_compare as any).comparison.summary }}
          </p>
          <el-table
            v-if="((optionsVol()?.strike_ladder as any)?.rows)?.length"
            :data="(optionsVol()?.strike_ladder as any).rows"
            size="small"
            stripe
            class="mt ladder-mini"
            max-height="200"
          >
            <el-table-column prop="strike" label="K" width="72" />
            <el-table-column label="Call 模/隐" min-width="100">
              <template #default="{ row }">
                {{
                  row.model?.expiry_itm_call != null
                    ? (row.model.expiry_itm_call * 100).toFixed(0) + "%"
                    : "—"
                }}
                /
                {{
                  row.implied?.expiry_itm_call != null
                    ? (row.implied.expiry_itm_call * 100).toFixed(0) + "%"
                    : "—"
                }}
              </template>
            </el-table-column>
            <el-table-column label="Put 模/隐" min-width="100">
              <template #default="{ row }">
                {{
                  row.model?.expiry_itm_put != null
                    ? (row.model.expiry_itm_put * 100).toFixed(0) + "%"
                    : "—"
                }}
                /
                {{
                  row.implied?.expiry_itm_put != null
                    ? (row.implied.expiry_itm_put * 100).toFixed(0) + "%"
                    : "—"
                }}
              </template>
            </el-table-column>
            <el-table-column label="Call" width="72">
              <template #default="{ row }">
                {{ row.purchase?.verdict || "—" }}
              </template>
            </el-table-column>
            <el-table-column label="Put" width="72">
              <template #default="{ row }">
                {{ row.purchase_put?.verdict || "—" }}
              </template>
            </el-table-column>
          </el-table>
          <router-link to="/crypto-options-vol" class="var-link mt">期权波动详情 →</router-link>
        </el-card>
        <el-card v-if="result && !polling" shadow="never" class="panel-card mt">
          <template #header>
            <div class="raw-head">
              <span>原始数据</span>
              <el-button link type="primary" @click="showRaw = !showRaw">
                {{ showRaw ? "收起" : "展开" }}
              </el-button>
            </div>
          </template>
          <pre v-if="showRaw" class="json-viewer">{{ JSON.stringify(result, null, 2) }}</pre>
          <p v-else class="muted small">技术人员可展开查看完整 JSON 结果。</p>
        </el-card>
        <el-alert v-if="error" type="error" :title="error" show-icon class="mt" />
        <div v-else-if="polling" v-loading="true" class="loading-box" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.mt {
  margin-top: 16px;
}
.mb {
  margin-bottom: 8px;
}
.cross-summary {
  font-size: 14px;
  line-height: 1.5;
  margin: 0;
}
.muted.small {
  font-size: 12px;
  color: var(--text-muted);
}
.var-link {
  display: inline-block;
  margin-top: 8px;
  font-size: 13px;
  color: var(--el-color-primary);
  text-decoration: none;
}
.var-link:hover {
  text-decoration: underline;
}
.news-headlines {
  margin: 0 0 8px;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.5;
}
.news-headlines li {
  margin-bottom: 4px;
}
.mr {
  margin-right: 6px;
}
.raw-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.json-viewer {
  margin: 0;
  padding: 12px;
  max-height: 360px;
  overflow: auto;
  font-size: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.loading-box {
  min-height: 80px;
  margin-top: 16px;
}
</style>
