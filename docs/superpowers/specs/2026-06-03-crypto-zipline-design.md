# Crypto Zipline Strategy Lab — Design Spec

**Status:** Approved — 2026-06-03  
**Scope:** zipline-reloaded backtest lab for crypto; 15m data pull on demand; **no** scheduler / alerts / live signal pipeline

## User decision (locked)

| Dimension | Choice |
|-----------|--------|
| Integration mode | **C — 仅研究/回测** |
| Relation to `combined_signal` | **无耦合** — 现有 analysis 周期与 ML/技术面信号不变 |
| Scheduling | **不参与** `SchedulerManager` / Bark / Webhook |
| Data cadence | **15m** K 线；用户在实验室手动「同步数据」或回测前自动拉取 |

## Goals

1. **策略实验室**：在 Web 侧栏独立入口，选择标的、策略、回测区间，一键运行 zipline-reloaded 回测。
2. **15m 数据**：复用现有 ccxt 增量同步（`sync_ohlcv`），timeframe=`15m`，落盘至 `data/crypto/CRYPTO_*/ohlcv_15m.csv`。
3. **Bundle + 回测**：将 CSV 转为 Zipline minute bundle（24/7 calendar），`run_algorithm` 输出绩效与交易记录。
4. **可复现**：每次回测写入 `run_id` 目录（参数、metrics、trades JSON），可在 UI 查看历史。

## Non-goals (MVP)

- 定时任务 `job_type=zipline`（后续若选 A/B 再扩展）
- Bark / schedule_alerts 联动
- 自动下单、perp bot 对接
- 实时/准实时「每 15 分钟自动跑策略出信号」
- 在 AnalyzeView / CryptoOps 嵌入 zipline 信号卡片
- 多交易所（MVP 仅 Binance via ccxt，与现有一致）
- 增量 bcolz append（MVP 用滚动窗口 re-ingest，见下文）

## Architecture

### High-level flow

```
用户打开「Crypto 策略实验室」
  → [可选] POST /crypto/zipline/sync  (15m ccxt 增量)
  → POST /crypto/zipline/backtest     (symbol, strategy, start, end, capital)
       → ohlcv_15m.csv → Zipline csvdir bundle ingest (rolling window)
       → run_algorithm(strategy, ...)
       → persist run artifact + return summary
  → GET  /crypto/zipline/runs         (历史列表)
  → GET  /crypto/zipline/runs/{id}    (详情 + 权益曲线点)
```

### Module layout

| File | Responsibility |
|------|----------------|
| `crypto_zipline_bundle.py` | 注册 project-local bundle；24/7 calendar；CSV → ingest；`ZIPLINE_ROOT=data/crypto/zipline/` |
| `crypto_zipline_runner.py` | 加载策略模块、`run_algorithm`、解析 perf/trades → JSON |
| `crypto_zipline_strategies/` | 内置策略：`ma_crossover.py`、`momentum_rsi.py`（标准 initialize/handle_data） |
| `crypto_zipline_storage.py` | 回测 run 元数据、trades、equity series 落盘 |
| `crypto_zipline_lab.py` | 编排：`sync_15m()` + `run_backtest()` 供 API 调用 |

Extend (minimal touch):

| File | Change |
|------|--------|
| `routes/crypto.py` | `/crypto/zipline/*` REST（sync / backtest / runs / strategies） |
| `CryptoZiplineLabView.vue` | 策略实验室 UI |
| `MainLayout.vue` + `router/index.ts` | 侧栏 + 路由 |
| `api/crypto.ts` | TypeScript 客户端 |
| `pyproject.toml` | optional extra `zipline = ["zipline-reloaded>=3.0.4"]` |

**Explicitly not modified (C):** `scheduler_manager.py`, `schedule_alerts.py`, `crypto_scheduler.py`, `AnalyzeView` signal cards.

### Bundle strategy (MVP)

**方案 1 — 滚动窗口 re-ingest（采用）**

- 每次回测前：读取 `ohlcv_15m.csv` 最近 N 天（默认 90，可配）
- 写入临时 csvdir → `zipline ingest crypto_ccxt_15m`
- 优点：与 Zipline 文档一致、实现量可控
- 缺点：回测启动慢（2–3 标的可接受；UI 显示进度/超时提示）

后续迭代可换增量 bcolz，接口不变。

### Bundle registration

- Bundle 名：`crypto_ccxt_15m`
- Calendar：`24/7`（exchange_calendars 或 zipline 内置 24/7）
- Asset symbol 映射：`BTC` → `CRYPTO_BTC` sid（与 qlib 命名一致）
- Root：`{data_dir}/zipline/`（不依赖 `~/.zipline`，通过 env `ZIPLINE_ROOT` 指向项目目录）

### Built-in strategies (MVP)

| id | 说明 | 参数 |
|----|------|------|
| `ma_crossover` | 快慢均线交叉 | fast=10, slow=30 |
| `momentum_rsi` | RSI 超买超卖 | period=14, oversold=30, overbought=70 |

策略通过 registry dict 暴露；API `GET /strategies` 返回列表与默认参数。

### Backtest output schema

```json
{
  "run_id": "uuid",
  "symbol": "BTC",
  "strategy": "ma_crossover",
  "timeframe": "15m",
  "start": "2026-03-01",
  "end": "2026-06-03",
  "capital_base": 100000,
  "metrics": {
    "total_return": 0.12,
    "sharpe": 1.1,
    "max_drawdown": -0.08,
    "trade_count": 42
  },
  "final_signal": {
    "position": "long|short|flat",
    "target_pct": 1.0,
    "bar_time": "2026-06-03T08:00:00+00:00"
  },
  "trades": [...],
  "equity_curve": [{"time": "...", "value": 100000}, ...],
  "generated_at": "...",
  "disclaimer": "回测结果仅供参考，不构成投资建议。"
}
```

`final_signal` 仅供实验室展示最后一根 bar 的策略状态，**不**写入 analysis report、**不**触发告警。

### Storage

```
data/crypto/
  CRYPTO_BTC/ohlcv_15m.csv          # ccxt 同步
  zipline/
    bundles/                         # ingested bcolz (gitignore 或可选提交)
    lab/
      runs.jsonl                     # run index
      {run_id}/
        params.json
        result.json
        trades.jsonl
```

大体积 bundle 目录默认加入 `.gitignore`（`data/crypto/zipline/bundles/`）。

### API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/crypto/zipline/strategies` | 可用策略与默认参数 |
| POST | `/api/v1/crypto/zipline/sync` | `{symbols[], exchange_id?}` 拉取 15m OHLCV |
| POST | `/api/v1/crypto/zipline/backtest` | 运行回测（可 `sync_first: true`） |
| GET | `/api/v1/crypto/zipline/runs?limit=20` | 历史 run 列表 |
| GET | `/api/v1/crypto/zipline/runs/{run_id}` | 单次详情 |
| GET | `/api/v1/crypto/zipline/status` | zipline 是否已安装、bundle 就绪、数据范围 |

未安装 zipline extra 时：`503` + `{detail: "Install with: uv sync --extra zipline"}`。

### Frontend — CryptoZiplineLabView

Route: `/crypto-zipline`  
侧栏：**Crypto 策略实验室**（与「组合回测」A 股区分）

Panels:

1. **数据** — 标的 multi-select、同步 15m 按钮、最近 bar 时间 / 行数
2. **回测配置** — 策略下拉、日期区间、初始资金、策略参数（动态表单）
3. **运行** — 提交回测、loading（ingest 可能 30–120s）、错误展示
4. **结果** — metrics 卡片、权益曲线（echarts 或现有 chart 组件）、trades 表格、最后一根 bar 仓位提示
5. **历史** — 最近 runs 列表，点击查看

### Dependencies

```toml
[project.optional-dependencies]
zipline = ["zipline-reloaded>=3.0.4"]
```

- Python：与项目一致 `>=3.11,<3.13`
- 与 numpy/pandas 版本需与 zipline-reloaded 兼容（CI/dev 文档注明 `uv sync --extra zipline`）

### Testing

- `test_crypto_zipline_bundle.py` — CSV → csvdir 格式转换（无 network）
- `test_crypto_zipline_runner.py` — mock `run_algorithm` 或 synthetic 小数据集
- `test_crypto_zipline_routes.py` — API smoke；未安装 zipline 时 503
- 不依赖真实 ccxt（sync 用 mock）

### Error handling

- ccxt 同步失败：返回 per-symbol errors，不阻塞其他标的
- ingest 超时：默认 180s，超时返回 504 + 建议缩短回测区间
- 数据不足（少于 strategy warmup bars）：400 + 明确 bar 数要求
- zipline 未安装：503 统一提示

### Security

- 无新增 API key；ccxt 仍用现有 `.env` Binance 配置
- 回测仅读本地 CSV + 写 lab 目录

### Disclaimer

所有 API 响应与 UI 固定展示：**回测结果仅供参考，不构成投资建议。**

## Future extensions (out of scope for C)

- 升级为 **A 并行双轨**：`job_type=zipline` + 15m 定时 + Bark 信号变化告警
- 增量 bundle ingest
- 用户上传自定义策略 Python 文件（沙箱）
- 与 RD-Agent 因子导出策略模板

## Approval

- [x] User reviewed this spec (2026-06-03)
- [x] Proceed to implementation plan (`docs/superpowers/plans/2026-06-03-crypto-zipline.md`)
