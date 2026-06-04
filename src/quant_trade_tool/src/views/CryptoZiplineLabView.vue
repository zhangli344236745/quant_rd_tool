<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  cryptoApi,
  type CryptoZiplineBacktestResult,
  type CryptoZiplineComboLeg,
  type CryptoZiplineRunSummary,
  type CryptoZiplineStrategy,
  type CryptoZiplineTimeframeOption,
} from "@/api/crypto";
import { extractError } from "@/api/http";
import EquityCurveChart from "@/components/EquityCurveChart.vue";

const dataDir = "data/crypto";

const loading = ref(false);
const syncing = ref(false);
const downloading = ref(false);
const running = ref(false);
const error = ref("");

const status = ref<{
  engines: string[];
  default_engine?: string;
  default_timeframe?: string;
  timeframes?: CryptoZiplineTimeframeOption[];
  combo_modes?: string[];
  zipline_installed: boolean;
  zipline_inprocess?: boolean;
  zipline_venv?: boolean;
  zipline_error?: string | null;
  symbols: Array<{
    symbol: string;
    timeframe?: string;
    ready: boolean;
    bars_count: number;
    last_bar?: string;
  }>;
} | null>(null);
const timeframeOptions = computed(() =>
  status.value?.timeframes?.length
    ? status.value.timeframes
    : [{ id: "15m", label: "15m", bar_minutes: 15 }],
);
const comboModeOptions = computed(() =>
  (status.value?.combo_modes ?? ["vote", "and", "or", "weighted"]).map((m) => ({
    value: m,
    label: m,
  })),
);
const settingUpVenv = ref(false);
const strategies = ref<CryptoZiplineStrategy[]>([]);
const runs = ref<CryptoZiplineRunSummary[]>([]);
const result = ref<CryptoZiplineBacktestResult | null>(null);

const symbolsText = ref("BTC,ETH");
const form = ref({
  symbol: "BTC",
  timeframe: "15m",
  strategy: "ma_crossover",
  use_combo: false,
  combo_mode: "vote" as "vote" | "and" | "or" | "weighted",
  combo_legs: [
    { strategy: "supertrend", weight: 1 },
    { strategy: "ema_rsi_filter", weight: 1 },
    { strategy: "macd_rsi_confirm", weight: 1 },
  ] as CryptoZiplineComboLeg[],
  start: "2026-01-01",
  end: "2026-06-03",
  capital_base: 100000,
  sync_first: true,
  force_reingest: false,
  engine: "auto" as "auto" | "pandas" | "zipline",
  fast: 10,
  slow: 30,
  rsi_period: 14,
  bb_period: 20,
  bb_std: 2,
  channel: 20,
  macd_fast: 12,
  macd_slow: 26,
  macd_signal: 9,
  vol_lookback: 20,
  vol_mult: 1.5,
  atr_len: 10,
  atr_factor: 3,
  max_position: 0.5,
  min_position: 0.15,
  dist_atr: 2,
  rsi_min: 45,
  rsi_max: 75,
  rsi_floor: 50,
  rsi_cap: 70,
  adx_threshold: 25,
  squeeze_lookback: 120,
  keltner_mult: 1.5,
  ichimoku_kijun: 26,
});

const selectedStrategy = computed(() =>
  strategies.value.find((s) => s.id === form.value.strategy),
);

function strategyParams(): Record<string, number> {
  const s = form.value.strategy;
  if (s === "momentum_rsi") {
    return { period: form.value.rsi_period, oversold: 30, overbought: 70 };
  }
  if (s === "bollinger_revert") {
    return { period: form.value.bb_period, std_mult: form.value.bb_std };
  }
  if (s === "donchian_breakout") {
    return { channel: form.value.channel };
  }
  if (s === "macd_cross") {
    return {
      fast: form.value.macd_fast,
      slow: form.value.macd_slow,
      signal: form.value.macd_signal,
    };
  }
  if (s === "volume_breakout") {
    return { lookback: form.value.vol_lookback, vol_mult: form.value.vol_mult };
  }
  if (s === "supertrend") {
    return { atr_len: form.value.atr_len, factor: form.value.atr_factor };
  }
  if (s === "supertrend_sized") {
    return {
      atr_len: form.value.atr_len,
      factor: form.value.atr_factor,
      max_position: form.value.max_position,
      min_position: form.value.min_position,
      dist_atr: form.value.dist_atr,
    };
  }
  if (s === "stoch_rsi") {
    return {
      rsi_period: form.value.rsi_period,
      stoch_period: 14,
      k_smooth: 3,
      d_smooth: 3,
      oversold: 20,
      overbought: 80,
    };
  }
  if (s === "golden_cross") {
    return { fast: form.value.fast, slow: form.value.slow };
  }
  if (s === "ema_rsi_filter") {
    return {
      fast: form.value.fast,
      slow: form.value.slow,
      rsi_period: form.value.rsi_period,
      rsi_min: form.value.rsi_min,
      rsi_max: form.value.rsi_max,
    };
  }
  if (s === "macd_rsi_confirm") {
    return {
      fast: form.value.macd_fast,
      slow: form.value.macd_slow,
      signal: form.value.macd_signal,
      rsi_period: form.value.rsi_period,
      rsi_floor: form.value.rsi_floor,
      rsi_cap: form.value.rsi_cap,
    };
  }
  if (s === "ema_trend" || s === "ma_crossover") {
    return { fast: form.value.fast, slow: form.value.slow };
  }
  if (s === "adx_trend") {
    return { period: form.value.rsi_period, adx_threshold: form.value.adx_threshold };
  }
  if (s === "keltner_breakout") {
    return { period: form.value.bb_period, atr_mult: form.value.keltner_mult };
  }
  if (s === "bb_squeeze") {
    return {
      bb_period: form.value.bb_period,
      bb_std: form.value.bb_std,
      squeeze_lookback: form.value.squeeze_lookback,
      bw_percentile: 20,
    };
  }
  if (s === "ichimoku_cloud") {
    return { tenkan: form.value.fast, kijun: form.value.ichimoku_kijun };
  }
  if (s === "vwap_trend") {
    return { lookback: form.value.vol_lookback };
  }
  const spec = selectedStrategy.value;
  if (spec?.default_params) {
    return { ...spec.default_params };
  }
  return { fast: form.value.fast, slow: form.value.slow };
}

async function loadStatus() {
  try {
    const { data } = await cryptoApi.ziplineStatus(dataDir, undefined, form.value.timeframe);
    status.value = data;
    if (data.default_engine === "zipline" && form.value.engine === "auto") {
      form.value.engine = "zipline";
    }
    if (data.default_timeframe && !timeframeOptions.value.find((t) => t.id === form.value.timeframe)) {
      form.value.timeframe = data.default_timeframe;
    }
  } catch {
    status.value = null;
  }
}

function addComboLeg() {
  const first = strategies.value[0]?.id ?? "ma_crossover";
  form.value.combo_legs.push({ strategy: first, weight: 1 });
}

function removeComboLeg(idx: number) {
  if (form.value.combo_legs.length > 1) {
    form.value.combo_legs.splice(idx, 1);
  }
}

function buildComboLegs(): CryptoZiplineComboLeg[] | undefined {
  if (!form.value.use_combo) return undefined;
  return form.value.combo_legs.map((leg) => ({
    strategy: leg.strategy,
    weight: leg.weight ?? 1,
  }));
}

async function downloadData(format: "csv" | "zip") {
  downloading.value = true;
  error.value = "";
  try {
    await cryptoApi.ziplineExportDownload({
      symbol: form.value.symbol,
      timeframe: form.value.timeframe,
      start: form.value.start,
      end: form.value.end,
      format,
      data_dir: dataDir,
      run_id: format === "zip" && result.value?.run_id ? result.value.run_id : undefined,
    });
    ElMessage.success(format === "zip" ? "ZIP 已下载" : "CSV 已下载");
  } catch (e) {
    error.value = extractError(e);
    ElMessage.error(error.value);
  } finally {
    downloading.value = false;
  }
}

async function setupZiplineVenv() {
  settingUpVenv.value = true;
  error.value = "";
  try {
    const { data } = await cryptoApi.ziplineSetupVenv();
    if (data.ok) {
      ElMessage.success("Zipline 环境已就绪");
      await loadStatus();
    } else {
      ElMessage.error(data.error || "安装失败");
    }
  } catch (e) {
    error.value = extractError(e);
    ElMessage.error(error.value);
  } finally {
    settingUpVenv.value = false;
  }
}

async function loadStrategies() {
  const { data } = await cryptoApi.ziplineStrategies();
  strategies.value = data.strategies || [];
  if (strategies.value.length && !strategies.value.find((s) => s.id === form.value.strategy)) {
    form.value.strategy = strategies.value[0].id;
  }
  applyDefaultParams();
}

function applyDefaultParams() {
  const spec = strategies.value.find((s) => s.id === form.value.strategy);
  if (!spec?.default_params) return;
  const p = spec.default_params;
  if ("fast" in p && form.value.strategy === "macd_cross") {
    form.value.macd_fast = Number(p.fast);
  } else if ("fast" in p && form.value.strategy === "macd_rsi_confirm") {
    form.value.macd_fast = Number(p.fast);
  } else if ("fast" in p) {
    form.value.fast = Number(p.fast);
  }
  if ("slow" in p && form.value.strategy === "macd_cross") {
    form.value.macd_slow = Number(p.slow);
  } else if ("slow" in p && form.value.strategy === "macd_rsi_confirm") {
    form.value.macd_slow = Number(p.slow);
  } else if ("slow" in p) {
    form.value.slow = Number(p.slow);
  }
  if ("period" in p && form.value.strategy === "bollinger_revert") {
    form.value.bb_period = Number(p.period);
  } else if ("period" in p) {
    form.value.rsi_period = Number(p.period);
  }
  if ("channel" in p) form.value.channel = Number(p.channel);
  if ("std_mult" in p) form.value.bb_std = Number(p.std_mult);
  if ("signal" in p) form.value.macd_signal = Number(p.signal);
  if ("lookback" in p) form.value.vol_lookback = Number(p.lookback);
  if ("vol_mult" in p) form.value.vol_mult = Number(p.vol_mult);
  if ("atr_len" in p) form.value.atr_len = Number(p.atr_len);
  if ("factor" in p) form.value.atr_factor = Number(p.factor);
  if ("max_position" in p) form.value.max_position = Number(p.max_position);
  if ("min_position" in p) form.value.min_position = Number(p.min_position);
  if ("dist_atr" in p) form.value.dist_atr = Number(p.dist_atr);
  if ("rsi_min" in p) form.value.rsi_min = Number(p.rsi_min);
  if ("rsi_max" in p) form.value.rsi_max = Number(p.rsi_max);
  if ("rsi_floor" in p) form.value.rsi_floor = Number(p.rsi_floor);
  if ("rsi_cap" in p) form.value.rsi_cap = Number(p.rsi_cap);
  if ("adx_threshold" in p) form.value.adx_threshold = Number(p.adx_threshold);
  if ("squeeze_lookback" in p) form.value.squeeze_lookback = Number(p.squeeze_lookback);
  if ("atr_mult" in p) form.value.keltner_mult = Number(p.atr_mult);
  if ("kijun" in p) form.value.ichimoku_kijun = Number(p.kijun);
  if ("tenkan" in p) form.value.fast = Number(p.tenkan);
}

watch(() => form.value.strategy, () => applyDefaultParams());
watch(() => form.value.timeframe, () => loadStatus());

async function loadRuns() {
  try {
    const { data } = await cryptoApi.ziplineRuns(dataDir, 15);
    runs.value = data.runs || [];
  } catch {
    runs.value = [];
  }
}

async function syncData() {
  syncing.value = true;
  error.value = "";
  const symbols = symbolsText.value.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
  try {
    const { data } = await cryptoApi.ziplineSync({
      symbols,
      data_dir: dataDir,
      timeframe: form.value.timeframe,
    });
    const ok = data.synced?.length ?? 0;
    const fail = data.errors?.length ?? 0;
    const tf = data.timeframe ?? form.value.timeframe;
    ElMessage.success(`${tf} 同步完成：${ok} 成功${fail ? `，${fail} 失败` : ""}`);
    await loadStatus();
  } catch (e) {
    error.value = extractError(e);
    ElMessage.error(error.value);
  } finally {
    syncing.value = false;
  }
}

async function runBacktest() {
  running.value = true;
  error.value = "";
  result.value = null;
  try {
    const { data } = await cryptoApi.ziplineBacktest({
      symbol: form.value.symbol,
      strategy: form.value.strategy,
      timeframe: form.value.timeframe,
      start: form.value.start,
      end: form.value.end,
      capital_base: form.value.capital_base,
      strategy_params: form.value.use_combo ? undefined : strategyParams(),
      strategy_combo: buildComboLegs(),
      combo_mode: form.value.combo_mode,
      sync_first: form.value.sync_first,
      force_reingest: form.value.force_reingest,
      engine: form.value.engine,
    });
    result.value = data;
    ElMessage.success(`回测完成（${data.engine}）`);
    await loadRuns();
  } catch (e) {
    error.value = extractError(e);
    ElMessage.error(error.value);
  } finally {
    running.value = false;
  }
}

async function openRun(runId: string) {
  loading.value = true;
  try {
    const { data } = await cryptoApi.ziplineRun(runId, dataDir);
    result.value = data;
  } catch (e) {
    ElMessage.error(extractError(e));
  } finally {
    loading.value = false;
  }
}

function pct(v: number | undefined) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

onMounted(async () => {
  loading.value = true;
  try {
    await Promise.all([loadStrategies(), loadStatus(), loadRuns()]);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div v-loading="loading">
    <h1 class="page-title">Crypto 策略实验室</h1>
    <p class="page-desc">
      多周期 K 线回测（5m–1d），支持多策略组合；优先 <strong>zipline-reloaded</strong>（<code>.venv-zipline</code>）。
      可下载 OHLCV / 回测结果。不参与定时任务与告警。
    </p>

    <el-card shadow="never" class="panel-card">
      <template #header>回测数据</template>
      <el-form inline size="small">
        <el-form-item label="周期">
          <el-select v-model="form.timeframe" style="width: 90px">
            <el-option
              v-for="tf in timeframeOptions"
              :key="tf.id"
              :label="tf.label"
              :value="tf.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标的">
          <el-input v-model="symbolsText" placeholder="BTC,ETH" style="width: 160px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="syncing" @click="syncData">同步 K 线</el-button>
        </el-form-item>
        <el-form-item>
          <el-button :loading="downloading" @click="downloadData('csv')">下载 CSV</el-button>
          <el-button :loading="downloading" @click="downloadData('zip')">下载 ZIP</el-button>
        </el-form-item>
      </el-form>
      <p v-if="status" class="muted small">
        引擎：{{ status.engines.join(", ") }}
        · Zipline {{ status.zipline_installed ? "可用" : "不可用" }}
        <template v-if="status.zipline_installed">
          （进程内 {{ status.zipline_inprocess ? "是" : "否" }} / 子环境 {{ status.zipline_venv ? "是" : "否" }}）
        </template>
        <el-button
          v-if="status && !status.zipline_installed"
          link
          type="primary"
          :loading="settingUpVenv"
          class="ml"
          @click="setupZiplineVenv"
        >
          安装 Zipline 环境
        </el-button>
      </p>
      <p v-if="status?.zipline_error && !status.zipline_installed" class="muted small error-hint">
        {{ status.zipline_error }}
      </p>
      <el-table v-if="status?.symbols?.length" :data="status.symbols" size="small" class="mt">
        <el-table-column prop="symbol" label="标的" width="80" />
        <el-table-column prop="timeframe" label="周期" width="60" />
        <el-table-column prop="bars_count" label="K 线数" width="90" />
        <el-table-column prop="last_bar" label="最近 bar" />
        <el-table-column label="就绪" width="70">
          <template #default="{ row }">
            <el-tag :type="row.ready ? 'success' : 'info'" size="small">{{ row.ready ? "是" : "否" }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="panel-card mt">
      <template #header>回测配置</template>
      <el-form label-width="100px" size="small">
        <el-form-item label="标的">
          <el-select v-model="form.symbol" style="width: 120px">
            <el-option label="BTC" value="BTC" />
            <el-option label="ETH" value="ETH" />
          </el-select>
        </el-form-item>
        <el-form-item label="周期">
          <el-select v-model="form.timeframe" style="width: 90px">
            <el-option
              v-for="tf in timeframeOptions"
              :key="tf.id"
              :label="tf.label"
              :value="tf.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="组合模式">
          <el-switch v-model="form.use_combo" active-text="多策略组合" />
        </el-form-item>
        <template v-if="form.use_combo">
          <el-form-item label="合成方式">
            <el-select v-model="form.combo_mode" style="width: 120px">
              <el-option
                v-for="m in comboModeOptions"
                :key="m.value"
                :label="m.label"
                :value="m.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="策略腿">
            <div class="combo-legs">
              <div v-for="(leg, idx) in form.combo_legs" :key="idx" class="combo-leg-row">
                <el-select v-model="leg.strategy" style="width: 180px" size="small">
                  <el-option
                    v-for="s in strategies"
                    :key="s.id"
                    :label="s.name"
                    :value="s.id"
                  />
                </el-select>
                <span class="leg-w">权重</span>
                <el-input-number v-model="leg.weight" :min="0.1" :max="10" :step="0.5" size="small" />
                <el-button
                  v-if="form.combo_legs.length > 1"
                  link
                  type="danger"
                  size="small"
                  @click="removeComboLeg(idx)"
                >
                  删除
                </el-button>
              </div>
              <el-button size="small" @click="addComboLeg">添加策略</el-button>
            </div>
          </el-form-item>
        </template>
        <el-form-item v-else label="策略">
          <el-select v-model="form.strategy" style="width: 200px">
            <el-option
              v-for="s in strategies"
              :key="s.id"
              :label="s.name"
              :value="s.id"
            />
          </el-select>
          <span v-if="selectedStrategy" class="hint">{{ selectedStrategy.description }}</span>
        </el-form-item>
        <el-form-item
          v-if="
            !form.use_combo &&
            (form.strategy === 'ma_crossover' ||
              form.strategy === 'ema_trend' ||
              form.strategy === 'golden_cross' ||
              form.strategy === 'ema_rsi_filter')
          "
          :label="
            form.strategy === 'golden_cross'
              ? 'SMA 50/200'
              : form.strategy === 'ema_trend' || form.strategy === 'ema_rsi_filter'
                ? 'EMA'
                : '均线'
          "
        >
          <el-input-number v-model="form.fast" :min="2" :max="100" /> /
          <el-input-number v-model="form.slow" :min="5" :max="250" />
        </el-form-item>
        <el-form-item
          v-else-if="
            !form.use_combo && (form.strategy === 'supertrend' || form.strategy === 'supertrend_sized')
          "
          label="Supertrend"
        >
          ATR <el-input-number v-model="form.atr_len" :min="5" :max="30" />
          倍数 <el-input-number v-model="form.atr_factor" :min="1" :max="6" :step="0.5" />
          <template v-if="form.strategy === 'supertrend_sized'">
            <span class="leg-w">仓位</span>
            <el-input-number v-model="form.min_position" :min="0.05" :max="0.9" :step="0.05" />
            –
            <el-input-number v-model="form.max_position" :min="0.1" :max="1" :step="0.05" />
            <span class="leg-w">距线(ATR)</span>
            <el-input-number v-model="form.dist_atr" :min="0.5" :max="5" :step="0.5" />
          </template>
        </el-form-item>
        <el-form-item
          v-else-if="
            !form.use_combo &&
            (form.strategy === 'momentum_rsi' ||
              form.strategy === 'stoch_rsi' ||
              form.strategy === 'ema_rsi_filter' ||
              form.strategy === 'macd_rsi_confirm')
          "
          label="RSI"
        >
          周期 <el-input-number v-model="form.rsi_period" :min="5" :max="50" />
          <template v-if="form.strategy === 'ema_rsi_filter'">
            区间 <el-input-number v-model="form.rsi_min" :min="20" :max="60" /> –
            <el-input-number v-model="form.rsi_max" :min="60" :max="90" />
          </template>
          <template v-if="form.strategy === 'macd_rsi_confirm'">
            确认 <el-input-number v-model="form.rsi_floor" :min="30" :max="60" /> –
            <el-input-number v-model="form.rsi_cap" :min="60" :max="85" />
          </template>
        </el-form-item>
        <el-form-item v-else-if="!form.use_combo && form.strategy === 'adx_trend'" label="ADX">
          周期 <el-input-number v-model="form.rsi_period" :min="7" :max="30" />
          阈值 <el-input-number v-model="form.adx_threshold" :min="15" :max="40" />
        </el-form-item>
        <el-form-item v-else-if="!form.use_combo && form.strategy === 'keltner_breakout'" label="Keltner">
          周期 <el-input-number v-model="form.bb_period" :min="10" :max="60" />
          ATR× <el-input-number v-model="form.keltner_mult" :min="1" :max="3" :step="0.1" />
        </el-form-item>
        <el-form-item v-else-if="!form.use_combo && form.strategy === 'bb_squeeze'" label="Squeeze">
          BB <el-input-number v-model="form.bb_period" :min="10" :max="40" />
          σ <el-input-number v-model="form.bb_std" :min="1" :max="3" :step="0.1" />
          回看 <el-input-number v-model="form.squeeze_lookback" :min="40" :max="300" :step="10" />
        </el-form-item>
        <el-form-item v-else-if="!form.use_combo && form.strategy === 'ichimoku_cloud'" label="Ichimoku">
          转换 <el-input-number v-model="form.fast" :min="5" :max="20" />
          基准 <el-input-number v-model="form.ichimoku_kijun" :min="20" :max="60" />
        </el-form-item>
        <el-form-item v-else-if="!form.use_combo && form.strategy === 'vwap_trend'" label="VWAP 回看">
          <el-input-number v-model="form.vol_lookback" :min="5" :max="100" />
        </el-form-item>
        <el-form-item v-else-if="!form.use_combo && form.strategy === 'bollinger_revert'" label="布林带">
          周期 <el-input-number v-model="form.bb_period" :min="10" :max="60" />
          σ <el-input-number v-model="form.bb_std" :min="1" :max="3" :step="0.1" />
        </el-form-item>
        <el-form-item v-else-if="!form.use_combo && form.strategy === 'donchian_breakout'" label="通道周期">
          <el-input-number v-model="form.channel" :min="5" :max="120" />
        </el-form-item>
        <el-form-item
          v-else-if="!form.use_combo && (form.strategy === 'macd_cross' || form.strategy === 'macd_rsi_confirm')"
          label="MACD"
        >
          <el-input-number v-model="form.macd_fast" :min="2" :max="50" /> /
          <el-input-number v-model="form.macd_slow" :min="5" :max="100" /> /
          <el-input-number v-model="form.macd_signal" :min="2" :max="30" />
        </el-form-item>
        <el-form-item v-else-if="!form.use_combo && form.strategy === 'volume_breakout'" label="放量突破">
          回看 <el-input-number v-model="form.vol_lookback" :min="5" :max="60" />
          倍数 <el-input-number v-model="form.vol_mult" :min="1" :max="5" :step="0.1" />
        </el-form-item>
        <el-form-item label="区间">
          <el-input v-model="form.start" style="width: 130px" /> —
          <el-input v-model="form.end" style="width: 130px" />
        </el-form-item>
        <el-form-item label="初始资金">
          <el-input-number v-model="form.capital_base" :min="1000" :step="10000" />
        </el-form-item>
        <el-form-item label="引擎">
          <el-select v-model="form.engine" style="width: 140px">
            <el-option label="自动" value="auto" />
            <el-option label="Pandas" value="pandas" />
            <el-option label="Zipline" value="zipline" />
          </el-select>
        </el-form-item>
        <el-form-item label="回测前同步">
          <el-switch v-model="form.sync_first" />
        </el-form-item>
        <el-form-item v-if="form.engine !== 'pandas'" label="强制重建 bundle">
          <el-switch v-model="form.force_reingest" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="running" @click="runBacktest">运行回测</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="error" type="error" :title="error" show-icon class="mt" />
    </el-card>

    <el-card v-if="result" shadow="never" class="panel-card mt">
      <template #header>
        回测结果 · {{ result.engine }}
        <span v-if="result.timeframe" class="hint">({{ result.timeframe }})</span>
      </template>
      <el-alert
        v-if="result.zipline_fallback_reason"
        type="warning"
        :title="'Zipline 未成功，已回退 pandas：' + result.zipline_fallback_reason"
        show-icon
        class="mb"
      />
      <div class="metrics">
        <el-tag type="info">总收益 {{ pct(result.metrics?.total_return) }}</el-tag>
        <el-tag type="info">Sharpe {{ result.metrics?.sharpe ?? "—" }}</el-tag>
        <el-tag type="warning">最大回撤 {{ pct(result.metrics?.max_drawdown) }}</el-tag>
        <el-tag>交易 {{ result.metrics?.trade_count ?? 0 }} 次</el-tag>
        <el-tag v-if="result.final_signal" type="success">
          末 bar {{ result.final_signal.position }} ({{ Math.round((result.final_signal.target_pct ?? 0) * 100) }}%)
        </el-tag>
        <el-tag v-if="result.bar_count" type="info">{{ result.bar_count }} bars</el-tag>
        <el-tag v-if="result.ingest_skipped" type="success">bundle 缓存命中</el-tag>
      </div>
      <EquityCurveChart
        v-if="result.equity_curve?.length"
        :data="result.equity_curve"
        :capital-base="result.capital_base"
        class="mt"
      />
      <p class="muted small mt">{{ result.disclaimer }}</p>
      <el-table
        v-if="result.trades?.length"
        :data="result.trades.slice(-20)"
        size="small"
        class="mt"
        max-height="240"
      >
        <el-table-column prop="time" label="时间" />
        <el-table-column prop="side" label="方向" width="70" />
        <el-table-column prop="price" label="价格" width="100" />
        <el-table-column prop="value" label="成交额" width="100" />
      </el-table>
    </el-card>

    <el-card shadow="never" class="panel-card mt">
      <template #header>历史回测</template>
      <el-empty v-if="!runs.length" description="暂无记录" />
      <el-table v-else :data="runs" size="small" @row-click="(row: CryptoZiplineRunSummary) => openRun(row.run_id)">
        <el-table-column prop="generated_at" label="时间" />
        <el-table-column prop="symbol" label="标的" width="70" />
        <el-table-column prop="timeframe" label="周期" width="56" />
        <el-table-column prop="strategy" label="策略" />
        <el-table-column prop="engine" label="引擎" width="80" />
        <el-table-column label="收益" width="90">
          <template #default="{ row }">{{ pct(row.total_return) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page-title {
  margin: 0 0 8px;
  font-size: 22px;
}
.page-desc {
  margin: 0 0 16px;
  color: var(--text-muted);
  font-size: 14px;
}
.panel-card {
  margin-bottom: 0;
}
.mt {
  margin-top: 12px;
}
.muted {
  color: var(--text-muted);
}
.small {
  font-size: 12px;
}
.hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-muted);
}
.metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.mb {
  margin-bottom: 12px;
}
.combo-legs {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.combo-leg-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.leg-w {
  font-size: 12px;
  color: var(--text-muted);
}
.ml {
  margin-left: 8px;
}
</style>
