# quant-rd-tool

基于 [uv](https://github.com/astral-sh/uv) 的 Python 环境，对接 [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent) 的金融量化场景，并提供可在本地直接调用的**股票因子计算**与**投资研报结构化** HTTP API。

## 环境（uv）

```bash
cd quant_rd_tool
uv sync
uv sync --extra dev
```

`uv sync` 已包含 **Microsoft `rdagent`** 包（体积较大）。官方 README 写明 RD-Agent 当前以 **Linux** 为主支持环境；macOS 上可先只用本工具的因子与研报 API，完整量化循环建议在 Linux 或容器内运行。

复制环境变量示例并填写 LLM（与 RD-Agent 相同，使用 LiteLLM / OpenAI 兼容配置）：

```bash
cp .env.example .env
```

## 产品双线（C+ 专业轨 + 企业 MVP 轨）

- **C+**：投研深度（报告版本/diff、选股器、SSE 任务等）— 见 [双线规格](docs/superpowers/specs/2026-05-30-dual-track-c-plus-enterprise-design.md)
- **企业 MVP**（默认关闭）：`GET /api/v1/enterprise/status` · API Key / 管理员登录 · 审计 `data/enterprise/audit.jsonl` · 设置页可配置

## 启动 API

```bash
uv run quant-rd serve
```

默认 `http://127.0.0.1:8765`，文档见 `http://127.0.0.1:8765/docs`。

## Web 控制台（Vue 3 + Element Plus）

界面化操作 crypto / 永续 bot / 定时任务。

**单端口（推荐）**：先构建前端，再由 FastAPI 托管 `dist/`：

```bash
cd src/quant_trade_tool && npm install && npm run build
cd ../.. && uv run quant-rd serve
# 控制台 http://127.0.0.1:8765/  ·  API 文档 http://127.0.0.1:8765/docs
uv run uvicorn quant_rd_tool.main:app --host 127.0.0.1 --port 18765
```

**开发模式**（热更新）：

```bash
uv run quant-rd serve          # 8765
cd src/quant_trade_tool && npm run dev   # 5173，Vite 代理 /api
```

详见 [src/quant_trade_tool/README.md](src/quant_trade_tool/README.md)。

### A 股公司库（akshare）

Web 控制台 **「A 股公司」**：全市场列表搜索、自选、基本信息（东财 + 巨潮）、管理层变动、新闻与公告、**后台 Qlib 分析任务**与报告回看。

- API：`GET /api/v1/stocks/list`、`GET /api/v1/stocks/{code}/profile|management|news|notices`
- 异步分析：`POST /api/v1/jobs/qlib-analyze` → `{ job_id }`，`GET /api/v1/jobs/{id}` 轮询状态
- 同步（脚本用）：`POST /api/v1/stocks/qlib-analyze/{code}?sync=1`
- 自选：`GET/POST/DELETE /api/v1/stocks/watchlist`
- 报告：`GET /api/v1/stocks/{code}/reports/latest`（含宏观摘要、技术字段）
- 报告库：`GET /api/v1/stocks/reports` · 对比：`GET /api/v1/stocks/reports/compare?code_a=&code_b=`
- Web：**报告库**、**两只对比**（`/astocks-reports`、`/astocks-compare`）

**统一任务中心**（Web 侧栏 / 顶栏「任务」）：

- `POST /api/v1/jobs/analyze-stock` — A 股完整分析
- `POST /api/v1/jobs/backtest` — 组合回测
- `POST /api/v1/jobs/macro-panel` — 宏观面板
- `POST /api/v1/jobs/crypto-analyze` — Crypto 分析
- `GET /api/v1/jobs/{id}/result` — 任务结果摘要

**开发服务**（代码变更自动重载）：

```bash
uv run quant-rd serve --reload
```

**ProxyError 排障**：系统 VPN/代理可能导致东财接口失败。在控制台 **设置 → 网络代理** 配置 `NO_PROXY`（含 `push2.eastmoney.com`），或清空代理后重启 `quant-rd serve`。

## 加密货币（ccxt + 币安机器人）

使用 **ccxt** 拉取币安现货 K 线，输出 **看涨 / 看跌 / 中性** 研判与文字建议；可选写入 **qlib** 目录。

### Alpha158 是什么（以及为什么这里用它）

本项目的 qlib 机器学习部分使用 Qlib 内置的 `Alpha158` 特征处理器（DataHandler）。

- **Alpha158 是什么**：从 OHLCV（开高低收量）自动构造的一组**标准化技术面特征**，大约 **158 维**（动量、波动、量价关系等）。
- **它的作用**：把原始 K 线数据变成可直接喂给模型的特征矩阵 \(X\)，并配套生成标签 \(y\)（本项目默认是“下一根收益”的代理标签），然后用 XGBoost / LightGBM 训练输出“偏多/偏空/中性”信号。
- **注意**：在单标的、短周期（如 5m）下，模型指标可能接近随机（IC/方向命中率接近 0.5），更适合当作辅助参考而非唯一依据。

**可运行的演示脚本（从本地 `qlib_5m/` 生成 Alpha158 特征）**：

```bash
# 先确保本地已有 BTC 5m 的 qlib 数据（会生成 data/crypto/CRYPTO_BTC/qlib_5m/）
uv run quant-rd crypto analyze --symbol BTC --timeframe 5m

# 运行演示：打印特征维度（≈158）、训练段行数、示例特征名等
uv run python src/tools/demo_alpha158.py
```

**对应的测试用例**（若本地没有 `qlib_5m` 数据会自动 skip）：

```bash
uv run pytest tests/test_alpha158_demo.py -q
```

```bash
# 连接自检（建议定时任务前先跑）
uv run quant-rd crypto ping
uv run quant-rd crypto ping --no-ohlcv   # 仅测 exchangeInfo

# 分析报告（无需 API Key；含 qlib Alpha158 + XGB/LGB，建议 1d & limit≥500）
uv run quant-rd crypto analyze --symbol BTC
uv run quant-rd crypto analyze --symbol ETH --ml-algo both
uv run quant-rd crypto analyze --symbol BTC --no-ml   # 仅技术面

# 仅跑 qlib ML（需已有 data/crypto/CRYPTO_BTC/）
uv run quant-rd crypto ml --symbol BTC --algo both

# 交易机器人（默认 dry-run，不真实下单）
uv run quant-rd crypto bot --symbol BTC --signal-only
uv run quant-rd crypto bot --symbol BTC --use-ml --signal-only  # 技术面+ML 综合信号
uv run quant-rd crypto bot --symbol ETH --amount 100

# 永续（USDT-M perpetual，默认 dry-run，不真实下单）
uv run quant-rd crypto perp-bot --base BTC --timeframe 5m --once
uv run quant-rd crypto perp-bot --base BTC --timeframe 5m --signal-only
# 风控：ATR 定仓（hybrid=波动止损定名义且不超过杠杆上限）+ ATR 保护单；熔断/软保护
uv run quant-rd crypto perp-bot --base BTC --sizing-mode hybrid --sl-atr 1.5 --tp-atr 2.5 --max-daily-loss-pct 0.03 --once
# 固定杠杆比例定仓（旧逻辑）
uv run quant-rd crypto perp-bot --base BTC --sizing-mode leverage_fraction --once
# 每轮决策写入 JSONL：data/crypto/perp_logs/YYYYMMDD.jsonl（含 decision / error_category）
uv run quant-rd crypto perp-bot --base BTC --once
tail -f data/crypto/perp_logs/$(date +%Y%m%d).jsonl

# 前台循环，每 10 分钟跑一轮（Ctrl+C 停止）
uv run quant-rd crypto perp-bot --base BTC --timeframe 5m --interval-minutes 10

# 测试网实盘（.env: BINANCE_TESTNET=true + API Key）
uv run quant-rd crypto perp-bot --base BTC --timeframe 5m --testnet --live --once

# 主网实盘（危险，需明确 --live）
uv run quant-rd crypto perp-bot --base BTC --timeframe 5m --live --once

# 多标的永续组合（一次跑 BTC+ETH，带组合预算与并发仓位约束）
uv run quant-rd crypto perp-portfolio --symbols BTC ETH --once
uv run quant-rd crypto perp-portfolio --symbols BTC ETH --signal-only
uv run quant-rd crypto perp-portfolio --symbols BTC ETH --total-notional 500 --max-per-symbol-notional 300 --max-concurrent 2 --once

# 测试网实盘（.env: BINANCE_TESTNET=true + API Key）
uv run quant-rd crypto bot --symbol BTC --testnet --live

# 主网实盘（危险，需明确 --live）
uv run quant-rd crypto bot --symbol BTC --live
```

**定时任务（每 30 分钟增量拉取 5m K 线 → qlib → 技术面 + ML 建议）**：

```bash
# 跑一轮（首次会回填约 90 天 5m 历史）
uv run quant-rd crypto schedule --symbols BTC ETH --once

# 后台循环，每 30 分钟执行
uv run quant-rd crypto schedule --symbols BTC ETH --interval-minutes 30

# 自定义周期与回填
uv run quant-rd crypto schedule --symbols BTC --timeframe 5m --backfill-days 120 --once --json-only
```

数据落盘：`data/crypto/CRYPTO_BTC/ohlcv_5m.csv`、`qlib_5m/`、`report.json`，快照在 `scheduler/5m/`。

**定时任务管理（注册 / 启停 / 列表）** — 任务定义保存在 `data/crypto/schedules.json`：

```bash
# 新增任务（不自动启动）
uv run quant-rd crypto schedule add --symbols BTC ETH --interval-minutes 30

# 查看任务列表
uv run quant-rd crypto schedule list

# CLI 前台启动（阻塞，Ctrl+C 停止）
uv run quant-rd crypto schedule start --id btc-eth-5m

# 手动跑一轮
uv run quant-rd crypto schedule run-once --id btc-eth-5m

# 删除任务
uv run quant-rd crypto schedule remove --id btc-eth-5m
```

通过 API 服务（`quant-rd serve`）可在后台启停：

- `GET /api/v1/crypto/schedules` — 任务列表
- `POST /api/v1/crypto/schedules` — 创建任务（`auto_start: true` 可立即启动）
- `POST /api/v1/crypto/schedules/{id}/start` — 后台启动
- `POST /api/v1/crypto/schedules/{id}/stop` — 停止
- `POST /api/v1/crypto/schedules/{id}/run-once` — 手动执行一轮
- `DELETE /api/v1/crypto/schedules/{id}` — 删除

HTTP（单次执行，不注册任务）：

- `POST /api/v1/crypto/schedule/run` — `{"symbols":["BTC","ETH"],"timeframe":"5m","once":true}`

其他 HTTP：

- `GET /api/v1/crypto/connectivity` — Binance/ccxt 连接自检
- `POST /api/v1/crypto/analyze` — `{"symbol":"BTC","with_ml":true,"ml_algorithm":"both"}`
- `POST /api/v1/crypto/ml` — `{"symbol":"BTC","algorithm":"both"}`
- `POST /api/v1/crypto/bot/run` — `{"symbol":"BTC","dry_run":true}`
- `POST /api/v1/crypto/perp-bot/run` — `{"base":"BTC","timeframe":"5m","dry_run":true}`
- `POST /api/v1/crypto/perp-portfolio/run` — `{"symbols":["BTC","ETH"],"dry_run":true,"signal_only":false}`
- `GET /api/v1/crypto/ops/summary` — 调度 + 永续状态 + 遥测摘要（Web **Crypto 运营** 看板）
- `GET/POST /api/v1/crypto/ops/control` — Kill Switch、Webhook 告警配置
- `POST /api/v1/crypto/ops/control/test-webhook` — 发送测试告警
- `GET/POST /api/v1/crypto/schedules/alerts/rules` — 调度失败/连续失败/卡住检测规则
- `GET /api/v1/crypto/schedules/alerts/log` — 告警 JSONL 历史
- `POST /api/v1/crypto/schedules/alerts/check-stale` — 手动检测长时间未跑完的 running 任务
- **按标的/信号自定义规则**：见 [docs/schedule-alert-custom-rules.md](docs/schedule-alert-custom-rules.md) · `GET .../schedules/alerts/rules/format`

**C+ P0（专业轨）**：

- 报告版本归档 + `GET /stocks/{code}/reports/diff`
- 任务 SSE：`GET /jobs/{id}/events` · 失败自动重试（`max_attempts`）
- 选股器：`POST /stocks/screener` · `POST /jobs/screener-enqueue` · Web **选股器**
- `GET /api/v1/crypto/perp/telemetry?day=YYYYMMDD&limit=100` — JSONL 遥测 tail
- `GET /api/v1/stocks/reports/export` — 打包本地 `report.json` / `report.md` 为 ZIP
- `GET /api/v1/crypto/perp/states` — 本地 `perp_state_*.json` 快照

`.env`：`BINANCE_API_KEY`、`BINANCE_API_SECRET`、`BINANCE_TESTNET=true`（建议先在测试网验证）。

## 与 RD-Agent CLI 的配合（Linux 推荐）

在已配置 `.env`（`CHAT_MODEL`、`EMBEDDING_MODEL`、`OPENAI_API_KEY` 等，参见 [RD-Agent 文档](https://rdagent.readthedocs.io/)）的机器上：

| 能力 | 命令 |
|------|------|
| 量化因子–模型联合迭代 | `uv run rdagent fin_quant` |
| 因子循环 | `uv run rdagent fin_factor` |
| 从财报文件夹抽取并实现因子 | `uv run rdagent fin_factor_report --report-folder=/path/to/reports` |

本仓库 API 中的 `POST /api/v1/rdagent/dispatch`：

- **`mode`（默认）`library`**：在当前服务进程内 **import `rdagent` 包** 并调用与 CLI 相同的入口函数（`rdagent.app.qlib_rd_loop.*.main`），通过 FastAPI `BackgroundTasks` 后台执行（与 `rdagent fin_quant` 等同源）。
- **`mode`: `subprocess`**：通过子进程执行 `rdagent` 可执行文件（需 PATH 中有 `rdagent`）。

`GET /api/v1/rdagent/status` 会同时返回 **`rdagent` 包版本** 与 **import 自检**（`library.imports_ok`）。

## 个股分析（独立功能）

输入一只 A 股代码：行情拉数（akshare / OpenBB）→ 本地 CSV + qlib 二进制 → 技术分析与风险指标 → 输出 `report.json` / `report.md`。

```bash
uv run quant-rd analyze --code 600519 --start 2020-01-01
uv run quant-rd analyze --code 600519 --refresh          # 强制重新下载
uv run quant-rd analyze --code 600519 --provider openbb  # 仅用 OpenBB（yfinance）
uv run quant-rd analyze --code 600519 --no-openbb        # 不拉 OpenBB 新闻/概况
uv run quant-rd analyze --code 600519 --md-only          # 仅打印 Markdown 报告
```

### OpenBB 数据层

已集成 [OpenBB Platform](https://docs.openbb.co/)（`openbb>=4`）：

| 能力 | 说明 |
|------|------|
| `--provider auto`（默认） | 先 **akshare**（东财/腾讯/新浪，前复权），失败再 **OpenBB** |
| `--provider akshare` | 仅国内源 |
| `--provider openbb` | `obb.equity.price.historical`（默认 yfinance，如 `600519.SS`） |
| 报告 enrichment | **宏观**（中国/美国 econdb 快照、CPI/GDP 序列、OECD 股指）+ **行业**（板块映射宏观同比、同业 peers 需 FMP Key）+ 公司概况 / 新闻 |

环境变量：`QUANT_RD_DATA_PROVIDER=auto|akshare|openbb`

> `openbb-akshare` 扩展与当前 `akshare>=1.18.62` 版本冲突，故 A 股仍以直连 akshare 为主；OpenBB 作备用与研报增强。若需 FMP 新闻等，在 OpenBB 文档中配置 `fmp_api_key`。

**单独宏观面板**（不跑完整 analyze）：

```bash
uv run quant-rd macro                              # 中国+美国宏观 → data/macro/
uv run quant-rd macro --code 600519              # 宏观 + 行业/同业（FMP 需 Key）
uv run quant-rd macro --countries china japan --md-only
uv run quant-rd macro --no-fred --output data/macro

# POST /api/v1/macro/panel
# {"countries":["china","united_states"], "code":"600519", "output_dir":"data/macro"}
```

`.env` 可选：`FRED_API_KEY`（FRED 利率/CPI/汇率序列）、`FMP_API_KEY`（同业 peers）。

**OpenBB 能力地图与研究包**（已融合进 analyze / backtest / macro）：

```bash
uv run quant-rd openbb caps              # 已接入的 OpenBB 端点清单
uv run quant-rd openbb caps --probe
uv run quant-rd openbb research --code 600519

# GET  /api/v1/openbb/capabilities
# POST /api/v1/openbb/research  {"code":"600519"}
```

| 模块 | OpenBB 能力 | 接入点 |
|------|-------------|--------|
| 行情 | `equity.price.historical` | `market_data` auto 回退 |
| 宏观 | econdb / OECD / FRED | `macro`、`analyze`、`backtest.openbb` |
| 行业 | profile + econdb 指标 + FMP peers | `analyze` |
| 基本面 | ratios / metrics (FMP/yfinance) | `analyze` |
| 预期 | consensus / price_target (FMP) | `analyze` |
| 日历 | earnings / dividend / 宏观日历 (FMP) | `analyze` |
| 技术面 | MACD / 布林 / ATR（本地 OHLCV 叠加） | `analyze` |
| 跨资产 | USD/CNY (yfinance)、FRED 汇率 | `analyze` |

本地目录结构：

```
data/stocks/SH600519/
  ohlcv.csv      # 原始 OHLCV
  qlib/          # calendars / instruments / features
  meta.json
  report.json
  report.md
```

HTTP：`POST /api/v1/analyze/stock`，body 字段 `code`、`start_date`、`data_dir`、`refresh`、`with_ml` 等。

### 机器学习（qlib Alpha158 + XGBoost / LightGBM）

在个股分析中默认启用（`--no-ml` 可关闭），支持 `--ml-algo xgb|lgb|both`：

```bash
uv run quant-rd ml --code 600519 --algo both
# POST /api/v1/ml/xgb  body: {"code":"600519", "algorithm":"both"}
```

**ML 信号回测**（用样本外预测做 Top-K 轮动，替代动量）：

```bash
uv run quant-rd backtest --symbols 600519 000858 601318 --signal ml --ml-algo lgb --start 2020-01-01
# POST /api/v1/backtest/run  "signal_mode": "ml", "ml_algorithm": "lgb"
```

输出：训练/验证/测试分段、IC、方向命中率、因子重要性、模型信号；回测额外含 `ml_summary`。

## 量化回测（行情 + qlib）

使用 **akshare / OpenBB** 拉取 A 股日线（`--provider auto`），写入 **qlib** 二进制数据格式，运行 **20 日动量 Top-K 等权轮动** 回测，并用 qlib 的 `risk_analysis` 计算夏普、最大回撤等，输出中文投资建议（研究用途）。

**环境**：`pyqlib` 目前仅支持 Python 3.11–3.12（项目已 pin `>=3.11,<3.13`）。推荐：

```bash
uv python pin 3.12
uv sync
```

### CLI

```bash
uv run quant-rd backtest
uv run quant-rd backtest --symbols 600519 000858 601318 --start 2024-01-01 --end 2024-12-31 --topk 3
```

### HTTP API

`POST /api/v1/backtest/run` — 请求体见 Swagger `/docs`。

```json
{
  "symbols": ["600519", "000858", "601318"],
  "start_date": "2023-01-01",
  "end_date": "2024-12-31",
  "lookback": 20,
  "topk": 3
}
```

响应中的 `advice` 字段包含立场（偏多/谨慎/中性）、要点与风险提示；`metrics` 为回测指标。

## 免责声明

市场数据来自第三方公开接口，因子、回测与研报内容仅供研究学习，不构成投资建议。
