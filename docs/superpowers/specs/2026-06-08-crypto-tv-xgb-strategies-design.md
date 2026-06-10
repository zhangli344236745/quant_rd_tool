# Crypto Zipline — TradingView 50 策略 + XGBoost 设计 Spec

**Status:** Approved — 2026-06-08  
**Parent:** [2026-06-03-crypto-zipline-design.md](./2026-06-03-crypto-zipline-design.md)  
**Scope:** 扩展 Crypto 策略实验室：50 个 TradingView 风格规则策略 + 3 类 XGBoost 策略；多周期回测；**无**调度/告警/实盘耦合

## User decisions (locked)

| Dimension | Choice |
|-----------|--------|
| XGB 集成模式 | **D — 全架构**：50 纯规则 TV 策略 + 独立 XGB + XGB 元模型集成 + XGB 过滤器 |
| 交付节奏 | **一次性全做**（同一迭代） |
| XGB 训练 | **Walk-forward**：回测区间内滚动训练，严格避免未来函数 |
| K 线周期 | **多周期**：5m / 15m / 30m / 1h / 4h / 1d |
| 集成模式 | **C — 仅研究/回测**（继承父 spec） |

## Goals

1. **50 个 TV 风格策略**：在现有 19 个基础上新增 31 个，统一 registry + signal 接口，可在 Zipline Lab 单独回测或 combo 组合。
2. **XGBoost 三层**：
   - `xgb_alpha158` — Alpha158 特征 walk-forward 方向策略
   - `xgb_tv_ensemble` — TV 信号矩阵 + Alpha158 元模型集成
   - `xgb_tv_filter` — 指定 TV 策略信号需 XGB 同向确认
3. **多周期**：策略 warmup / ML 训练窗口随 timeframe 自适应缩放。
4. **UI 可发现性**：50+ 策略按类别分组、可搜索；ML 策略有独立参数面板。

## Non-goals

- 做空 / 杠杆（保持 long-only 0/1 target）
- Pine Script 运行时转译或 TV webhook 对接
- 与 `combined_signal`、Bark、Scheduler 联动
- 用户上传自定义策略文件
- 实时推理服务（仅回测内 walk-forward）

## Current state

| 已有 | 说明 |
|------|------|
| 19 策略 | `crypto_zipline_strategies/__init__.py` + `signals.py` |
| pandas / zipline 双引擎 | `crypto_zipline_runner.py`, `zipline_algos.py` |
| combo | vote / and / or / weighted |
| 多周期 | `crypto_zipline_timeframes.py`（5m–1d） |
| ML 分析 | `crypto_ml.py` + `qlib_ml.py`（Alpha158 + XGB/LGB，用于行情分析，**未**接入 zipline 回测） |

## Architecture

### High-level flow

```
OHLCV DataFrame (任意 timeframe)
  │
  ├─► TV Signal Layer: 50 × signal_for_strategy() → matrix [bars × 50]
  │
  ├─► Feature Layer: Alpha158 (qlib) + optional TV rolling stats
  │
  ├─► Rule strategies: 各 TV id → target series → pandas/zipline backtest
  │
  └─► ML strategies (walk-forward):
        xgb_alpha158      → XGB(Alpha158) → target
        xgb_tv_ensemble   → XGB(Alpha158 + TV matrix) → target
        xgb_tv_filter     → TV(base_id) AND XGB → target
```

### Module layout

| File | Responsibility |
|------|----------------|
| `crypto_zipline_strategies/tv_catalog.py` | 50 策略元数据：id, name, category, tv_ref, default_params, min_bars |
| `crypto_zipline_strategies/signals_trend.py` | 趋势类 signal 函数 |
| `crypto_zipline_strategies/signals_momentum.py` | 动量类 signal 函数 |
| `crypto_zipline_strategies/signals_volume.py` | 成交量类 signal 函数 |
| `crypto_zipline_strategies/signals_volatility.py` | 波动类 signal 函数 |
| `crypto_zipline_strategies/signals.py` | 聚合 re-export + `signal_for_strategy()` 路由 |
| `crypto_zipline_strategies/__init__.py` | `STRATEGY_REGISTRY` 扩展至 50 + 3 ML |
| `crypto_zipline_ml_features.py` | Alpha158 + TV matrix 特征构建（无未来泄漏） |
| `crypto_zipline_ml.py` | walk-forward XGB 训练/推理、三 ML runner |
| `crypto_zipline_timeframes.py` | 新增 `ml_window_scale(timeframe)` |
| `crypto_zipline_strategies/zipline_algos.py` | ML 策略 handle_data 分支 |
| `routes/crypto.py` | strategies 响应增加 category/source |
| `CryptoZiplineLabView.vue` | 分组下拉、搜索、ML 参数 |
| `api/crypto.ts` | TypeScript 类型扩展 |

### Strategy catalog (50 TV rule strategies)

**Existing 19** (unchanged ids):  
`ma_crossover`, `ema_trend`, `momentum_rsi`, `bollinger_revert`, `donchian_breakout`, `macd_cross`, `volume_breakout`, `supertrend`, `supertrend_sized`, `stoch_rsi`, `golden_cross`, `ema_rsi_filter`, `macd_rsi_confirm`, `adx_trend`, `psar_trend`, `keltner_breakout`, `bb_squeeze`, `ichimoku_cloud`, `vwap_trend`

**New 31**:

| Category | id | TV reference / notes |
|----------|-----|----------------------|
| trend | `hull_ma_trend` | Hull MA vs price |
| trend | `dema_cross` | DEMA fast/slow cross |
| trend | `t3_ma_trend` | T3 MA trend |
| trend | `alma_trend` | ALMA vs price |
| trend | `zero_lag_ema` | ZLEMA trend |
| trend | `ssl_channel` | SSL Channel (TV community) |
| trend | `chandelier_exit` | Chandelier Exit long |
| trend | `aroon_trend` | Aroon Up > Down |
| trend | `linreg_channel` | Linear reg channel breakout |
| momentum | `williams_r` | Williams %R oversold/overbought |
| momentum | `cci_revert` | CCI mean reversion |
| momentum | `tsi_momentum` | True Strength Index |
| momentum | `ultimate_osc` | Ultimate Oscillator |
| momentum | `wavetrend` | LazyBear WaveTrend |
| momentum | `fisher_transform` | Fisher Transform cross |
| momentum | `connors_rsi` | Connors RSI |
| momentum | `rci_trend` | RCI 3-lines trend |
| momentum | `coppock_curve` | Coppock Curve momentum |
| momentum | `kst_momentum` | Know Sure Thing |
| volatility | `squeeze_momentum` | LazyBear SQZMOM |
| volatility | `keltner_squeeze` | Keltner inside BB squeeze break |
| volatility | `atr_breakout` | ATR channel breakout |
| volume | `mfi_revert` | Money Flow Index |
| volume | `obv_trend` | OBV vs MA trend |
| volume | `chaikin_mf` | Chaikin Money Flow |
| volume | `vwap_cross` | Price cross rolling VWAP |
| combo | `heikin_ashi_trend` | Heikin-Ashi consecutive bull |
| combo | `elder_impulse` | Elder Impulse (EMA + MACD hist) |
| combo | `tdi_dynamic` | Traders Dynamic Index |
| combo | `ut_bot` | UT Bot Alerts simplified |
| combo | `range_filter` | Range Filter trend |

> 注：上表 31 个 id 与现有 19 个合计 50。`tv_catalog.py` 为单一事实来源；registry 从 catalog 生成或校验计数。

**ML strategies (+3)**:

| id | name | description |
|----|------|-------------|
| `xgb_alpha158` | XGB Alpha158 | Walk-forward XGB on qlib Alpha158 |
| `xgb_tv_ensemble` | XGB TV 集成 | Alpha158 + 50 TV signals meta-model |
| `xgb_tv_filter` | XGB TV 过滤 | param `base_strategy` + XGB confirm |

### Walk-forward XGB parameters

| Param | Default (15m) | Notes |
|-------|---------------|-------|
| `train_bars` | 2000 | Scaled by `ml_window_scale(tf)` |
| `retrain_every` | 500 | Retrain interval in bars |
| `label_horizon` | 1 | Next-bar return sign |
| `min_train_samples` | 500 | Below → hold previous target |
| `xgb_threshold` | 0.0 | Pred > threshold → long |

**No look-ahead:** at bar index `t`, training uses `[t - train_bars, t)` only; prediction applies at `t`; position effective from `t+1` (or same bar per existing backtest convention — **must match pandas runner**, document in tests).

### Multi-timeframe scaling

```python
ML_WINDOW_SCALE = {
    "5m": 1.0, "15m": 1.0, "30m": 0.75,
    "1h": 0.25, "4h": 0.1, "1d": 0.05,
}
```

`effective_train_bars = int(default_train_bars * ML_WINDOW_SCALE[tf])`  
Strategy `min_bars` unchanged per strategy; ML warmup = `effective_train_bars + max_tv_min_bars`.

### API changes

`GET /api/v1/crypto/zipline/strategies` response item:

```json
{
  "id": "wavetrend",
  "name": "WaveTrend",
  "description": "...",
  "category": "momentum",
  "source": "tv",
  "tv_ref": "LazyBear WT",
  "default_params": {...},
  "min_bars": 35
}
```

ML strategies include `"source": "ml"` and extra defaults (`train_bars`, `retrain_every`, `base_strategy` for filter).

Backtest request unchanged; `strategy_params` carries ML knobs.

### Frontend

- Strategy `el-select`: `el-option-group` by category (趋势/动量/波动/成交量/组合/ML)
- Filterable search on 50+ names
- When `source === 'ml'`: show train_bars, retrain_every; when `xgb_tv_filter`, show base_strategy picker
- Result panel: optional ML metrics block (last OOS IC, hit rate, top features)

### Testing

| File | Coverage |
|------|----------|
| `tests/test_tv_signals.py` | Each new signal: warmup None, boundary values |
| `tests/test_tv_catalog.py` | Exactly 50 TV ids, unique, registry sync |
| `tests/test_crypto_zipline_ml.py` | Walk-forward no future leak; retrain boundaries |
| `tests/test_crypto_zipline_ml_strategies.py` | End-to-end pandas backtest for 3 ML ids |
| Update `tests/test_crypto_zipline_routes.py` | strategies count ≥ 53 |

Synthetic OHLCV fixtures only; no network.

### Performance

- Precompute full TV signal matrix once per backtest (O(bars × 50))
- Cache Alpha158 feature frame per backtest
- Walk-forward retrain only every `retrain_every` bars
- Default engine `pandas`; zipline path uses same target series precomputed where possible

### Error handling

- Insufficient bars for ML: 400 with required vs actual bar count
- qlib/Alpha158 failure: fallback message; optional degrade to TV-only for ensemble
- Unknown `base_strategy` in filter: 400

### Security & disclaimer

- No new secrets; local CSV + qlib only
- All responses include research disclaimer (inherit parent spec)

## Risks

| Risk | Mitigation |
|------|------------|
| 50 strategies × ML slow | Matrix precompute + sparse retrain |
| Alpha158 short history on 5m | Adaptive min_train + clear UI error |
| Overfitting | Walk-forward + report OOS IC in result |
| signals.py bloat | Split into category modules |

## Approval

- [x] User approved design in chat (2026-06-08)
- [x] Implementation plan: `docs/superpowers/plans/2026-06-08-crypto-tv-xgb-strategies.md`
