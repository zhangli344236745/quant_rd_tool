## 背景

当前 `quant_rd_tool` 已具备：

- 信号生成：`analyze_crypto → combined_signal(action/confidence/reasons)`
- 永续 one-way 交易骨架：`BinancePerpBot`（先平后开、amount 下单、bar_end 去重、CLI/API）

但仍缺少“可用交易系统”的关键层：风控（SL/TP/熔断）、动态仓位、执行幂等、以及多标的与观测。

本 spec 目标是定义下一阶段的交易机器人增强：**风控 + 执行层 + 多标的 + 状态观测**，并保持与现有信号管线解耦。

---

## 总体目标（下一阶段）

- **风险控制**：
  - 每笔仓位带 **止损/止盈（SL/TP）**
  - 支持 **日内亏损熔断 / 最大回撤熔断**（先做简单 wallet-based）
- **动态仓位**：
  - 用 `confidence` + 波动（ATR 或近 N bar 波动）决定名义仓位
  - 单标的/总仓位上限
- **执行层升级**：
  - 订单幂等（`clientOrderId`）
  - 交易所原生条件单（STOP_MARKET / TAKE_PROFIT_MARKET）为主，失败回退软止损（你选 C）
  - 翻转方向：**先 reduceOnly 平仓，再开新方向，并重建保护单**
- **多标的**：
  - 同一进程循环处理 BTC/ETH/...，组合风险预算
- **状态与观测**：
  - 持久化仓位/保护单/去重状态
  - 结构化日志输出；可选 webhook/telegram 通知（先预留接口）

非目标（本轮不做）：
- Paper trading / 回放模式
- 限价分批/TWAP（可在执行层留扩展点）
- Hedge mode（双向持仓）

---

## 关键决策（已确认）

- **持仓模式**：One-way（信号翻转先平后开）
- **SL/TP 下单方式**：C（默认下交易所原生条件单；失败回退软止损/止盈）
- **触发价基准**：A（`last` 最新价）
- **保护单失败默认策略**：C（先启用软止损/止盈并继续补挂；连续 N 轮失败则强制平仓）
- **幂等粒度（clientOrderId）**：A（按 `(symbol, bar_end, target_side)`；同一根 bar 同方向只执行一次）

---

## 架构分层

### 1) Signal Adapter（信号适配层）

职责：把 `combined_signal` 转成标准化目标（仅表达意图，不负责下单）。

输出：
- `target_side ∈ {long, short, flat}`
- `confidence ∈ [0,1]`
- `reasons[]`
- `bar_end`（用于幂等/去重）

说明：
- 仍复用 `analyze_crypto(base, timeframe=5m, ...)`
- 不在此层做风险或仓位

### 2) Risk Engine（风控与仓位层）

输入：
- `free_usdt`（期货账户）
- `confidence`
- 波动指标（ATR 或简化波动 proxy）
- 当前仓位（side/amount/entry）

输出：
- `desired_notional_usdt`（目标名义敞口）
- `sl_price` / `tp_price`（基于 `last` 与 ATR/百分比）
- `circuit_breaker` 状态（allow_trade / blocked + reason）

初版实现（建议）：
- **仓位**：`notional = free_usdt * total_risk_fraction * clamp(confidence, c_min, c_max)`
- **SL/TP**：
  - 方案 A：固定百分比（如 SL=1.0%，TP=1.5%）
  - 方案 B（推荐）：ATR 倍数（如 SL=1.5*ATR，TP=2.5*ATR）
  - 初版可先做 B（ATR 可从最近 OHLCV 计算）
- **熔断**：
  - 记录当日起始 `USDT_total`，若跌破阈值（例如 -3%）则停止开新仓，只允许平仓

### 3) Execution Engine（执行层）

职责：把“目标仓位 + 风控结果”变成一组可执行动作（close/open + protective orders），并保证幂等与容错。

关键能力：
- **clientOrderId 幂等**
  - 为每个 symbol 每个 bar_end 生成稳定的 `clientOrderId`
  - 唯一键：`(symbol, bar_end, target_side)`
  - 重复执行时，优先从本地 state 去重；可选 best-effort 查 open orders 做补充
- **下单顺序**
  - 若 flip：reduceOnly 市价全平 → 市价开仓 → 下保护单
  - 若 flat 且配置 `hold_behavior=close_position`：reduceOnly 平仓
- **保护单（优先交易所原生）**
  - stop：`STOP_MARKET` + `reduceOnly=true`
  - take profit：`TAKE_PROFIT_MARKET` + `reduceOnly=true`
  - 参数要点（Binance futures 常见要求）：
    - 两类条件单都需要 `stopPrice`
    - `workingType` 显式设置（尽管本轮触发价基准选择 `last`，也保留配置能力）
  - 若交易所/ccxt 参数不兼容：
    - 记录错误 → 启用 soft SL/TP（下轮轮询价格触发市价平仓）
    - 下一轮继续尝试补挂交易所原生保护单
    - 若连续 N 轮仍无法挂上（N 默认 3，可配）→ **强制市价平仓**（reduceOnly）
- **价格源**：`fetch_ticker().last`（last）；必要时 fallback close/bid/ask-mid

### 4) Portfolio Runner（多标的调度层）

职责：循环 symbols 列表，串行（或未来并行）运行每个 symbol 的 “signal→risk→exec”。

组合约束（初版）：
- `max_total_exposure_usdt`
- `max_per_symbol_exposure_usdt`
- `max_concurrent_positions`

### 5) State + Telemetry（状态与观测）

持久化：
- `last_seen_bar_end`（已有）
- `last_action`
- `position_snapshot`（side/amount/entry）
- `protective_orders`（stop/tp：orderId/clientOrderId/price）
- `daily_pnl_snapshot`（用于熔断）
 - `protection_fail_streak`（连续保护单失败次数，用于 C 策略强制平仓）

输出：
- 每轮 JSON log（可落盘到 `data/crypto/perp_logs/YYYYMMDD.jsonl`）
- 可选通知接口（先定义函数签名，默认 no-op）

---

## 接口形状（对外）

### CLI（扩展）

在已有 `quant-rd crypto perp-bot` 基础上扩展参数：
- 多标的：`--symbols BTC ETH`
- 风控：`--sl-atr 1.5 --tp-atr 2.5` 或 `--sl-pct 0.01 --tp-pct 0.015`
- 熔断：`--max-daily-loss-pct 0.03`
- 执行：`--use-native-protection/--no-native-protection`（默认开，失败回退软）

### API（扩展）

新增一个多标的 run-once endpoint（建议）：
- `POST /api/v1/crypto/perp-portfolio/run`

入参包含 symbols + 风控/执行参数，返回每个 symbol 的 cycle 结果数组。

---

## 边界条件与容错（必须覆盖）

- ccxt/binance 对条件单参数差异：必须有 fallback（软 SL/TP）
- 条件单部分失败：允许 “仅 SL” 或 “仅 TP” 暂存，但必须进入 `protection_fail_streak` 逻辑并在 N 轮后强制平仓
- 网络/地区限制：可用 proxy 与 `BINANCE_API_BASE`；并避免无关 market discovery（已修）
- 进程重启：state 落盘确保不重复交易；保护单状态尽量在下一轮 reconcile
- one-way vs hedge：检测到 hedge（多行仓位）则 fail-fast

