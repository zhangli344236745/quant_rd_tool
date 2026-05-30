## 背景与目标

在 `quant_rd_tool` 中完善一个**币安 USDT-M 永续**交易机器人，机器人每 **10 分钟**调用现有的加密分析/预测管线（`analyze_crypto → combined_signal`），把预测信号转成交易动作，并通过 **ccxt** 在币安永续执行。

核心目标：

- **可长期运行**：10 分钟循环，异常不崩溃，持续重试
- **单向持仓（One-way）**：信号翻转时 **先平仓，再反手开仓**
- **风控优先**：默认 dry-run；明确的名义金额/杠杆/最小名义限制；避免重复交易
- **可观测**：每轮输出结构化结果（signal / position / orders / errors）
- **对现有代码影响最小**：现货 bot/分析/定时任务保持兼容

非目标（本轮不做）：

- 多标的组合管理、资金分配优化
- 限价单/挂单队列、分批成交、TWAP
- 止损止盈 OCO / 条件单（如需可后续增量）
- 对冲模式（hedge）双向持仓

---

## 现有能力与接入点

### 信号源（已存在）

- `quant_rd_tool.crypto_analysis.analyze_crypto(...)` 生成 report
- report 的 `combined_signal`（也在 `signal` 字段中镜像）包含：
  - `action`: `buy | sell | hold`
  - `stance`: `看涨 | 看跌 | 中性`
  - `confidence`: 0~1
  - `reasons`: 原因列表

### 现货 bot（已存在）

- `quant_rd_tool.binance_bot.BinanceBot`：可 dry-run / spot 市价单

### 永续 bot（已存在的骨架，本轮将完善）

- `quant_rd_tool.binance_perp_bot.BinancePerpBot`：目前能跑 `run_once()`，但需要补齐：
  - 仓位感知（position）
  - 先平后开（flip）
  - `amount` 精度与最小名义（替代 `cost`）
  - 10 分钟循环与去抖
  - CLI 入口

---

## 交易模型（One-way）

### 目标仓位定义

统一抽象：

- `target_side ∈ {long, short, flat}`

映射规则：

- `combined_signal.action == "buy"` → `target_side = long`
- `combined_signal.action == "sell"` → `target_side = short`
- `combined_signal.action == "hold"` → `target_side = flat` **或**保持不动（可配置）

本轮默认策略：

- `hold_behavior = "do_nothing"`（信号 hold 时不交易、不主动平仓）

### 当前仓位识别

通过 ccxt futures：

- `fetch_positions([symbol], {"type":"future"})`（优先）
- 失败时降级：`fetch_position(symbol, {"type":"future"})`（若交易所实现）

归一化为：

- `position_side ∈ {long, short, flat}`
- `position_amount`（基础币数量 / 合约数量，按 ccxt 返回）
- `entry_price`（若有）

判定：

- `contracts/positionAmt` 接近 0（阈值）→ flat
- >0 → long；<0 → short
 - 若返回同一 symbol 多行（疑似 hedge 或多腿），默认 fail-fast 并提示用户修正账户模式/配置（本轮不支持 hedge）

### 执行策略（先平后开）

每轮执行：

1. 拉取信号，得到 `target_side`
2. 拉取当前仓位 `position_side`
3. 决策：
   - 若 `target_side == position_side`：**不动作**
   - 若 `target_side == flat`：
     - `hold_behavior == do_nothing`：不动作
     - `hold_behavior == close_position`：若有仓则 reduceOnly 全平
   - 若 `target_side` 与 `position_side` 相反：
     - **先** reduceOnly 市价全平（close）
     - **再** 市价开新方向仓位（open）

---

## 下单与数量计算（核心）

### 关键约束

永续下单应优先使用 **`amount`**，避免对 `cost` 参数的兼容性假设。

### 计算流程

输入参数：

- `free_usdt`: 期货账户可用 USDT
- `usdt_risk_fraction`: 每次用于建仓的资金占比（如 0.2）
- `leverage`: 杠杆（如 3）
- `min_notional_usdt`: 最小名义金额（默认 10）

步骤：

1. `notional = free_usdt * usdt_risk_fraction * leverage`
2. 若 `notional < min_notional_usdt` → skip
3. `price = fetch_ticker(symbol).last`（必要时容错：mid/ask/bid）
4. `raw_amount = notional / price`
5. 根据 `market` 精度/最小数量约束做 round/clip：
   - `amount = ex.amount_to_precision(symbol, raw_amount)`
   - 校验 `market.limits.amount.min`（若存在）
   - 校验 `market.limits.cost.min`（若存在）
   - 若 `market.limits.cost.min` 缺失，尝试从 `market.info.filters`（如 `MIN_NOTIONAL`/`LOT_SIZE`）推断
6. **后验校验**：`amount * price >= min_notional`，否则 skip（或按配置 bump 到最小）

### 平仓单（reduceOnly）

- 平仓使用 `reduceOnly=true`
- 平仓 `amount` 取当前仓位绝对值，精度同上

---

## 风控与保护开关

默认值（可在 config / API request 覆盖）：

- `dry_run=True`：默认不真实下单
- `min_notional_usdt=10`
- 账户模式保护：
  - 若检测到 **Hedge Mode**（双向持仓）则默认 **拒绝交易**（除非显式开启 hedge 支持）
  - `margin_mode`: `cross | isolated`（默认 cross；若无法设置/验证，输出 warning，并可配置为 hard-fail）
- `max_leverage`（可选，若传入 leverage > max 则 clamp）
- `position_epsilon`: 判定 flat 的仓位阈值（例如 1e-8 或交易所最小单位）
- 去抖：
  - `last_seen_bar_end`（来自 report.period.end）
  - 若同一 `bar_end` 重复触发，则不重复下单
  - **需要持久化**（state file），避免进程重启后重复交易

---

## 可靠性与错误策略

- transient 错误（网络超时、rate limit、时间戳偏差 `-1021` 等）：
  - 记录错误
  - 采用退避重试（同一轮最多 N 次；下一轮继续）
- hard 错误（鉴权、无权限、余额/保证金不足、symbol 不存在）：
  - 结构化输出并跳过下单
  - 根据配置决定是否停止循环

---

## 运行形态

### run-once

- API：`POST /api/v1/crypto/perp-bot/run`
- 支持 `signal_only=true`（只返回信号，不做交易决策/下单）

### run-forever（10 分钟循环）

新增：

- `BinancePerpBot.run_forever()`：
  - 每轮 try/except，记录异常
  - sleep 到下一轮（基于 `interval_minutes`，并减去执行耗时）

---

## 接口与配置

### 配置来源

- `.env`：
  - `BINANCE_API_KEY`
  - `BINANCE_API_SECRET`
  - `BINANCE_TESTNET`（可选）
- API Request body 覆盖（如 leverage, risk_fraction, timeframe）

### Symbol 约定

默认永续交易对：

- `"{base}/{quote}:{quote}"`，例如 `"BTC/USDT:USDT"`

并提供 `ccxt_symbol` 显式覆盖（防止交易所/ccxt 变体差异）。

---

## 观测与输出（结构化）

每轮返回/日志输出包含：

- `signal`：combined_signal（含 confidence/reasons）
- `target_side` 与 `position_side`
- `balance_before`
- `orders`：close_order / open_order（若有）
- `message` 与 `error`（若有）

---

## 测试计划（最小但有效）

- 单元：
  - `decide_action` / `target_side` 映射
  - amount/notional 计算（用 mock ticker/market 限制）
  - flip 决策树（flat/同向/反向）
- 集成（dry-run）：
  - `uv run python -c ...` 能 import
  - `uv run quant-rd serve` 后调用 API `perp-bot/run` dry_run 返回计划单结构

---

## 风险与注意事项

- 币安永续权限/模式（one-way/hedge）可能需要账户侧配置；本轮按 one-way 假设实现
- `fetch_positions` / `set_leverage` 在不同 ccxt 版本/交易所实现差异较大，需要容错
- 网络/地区访问限制：需要 proxy 或 `BINANCE_API_BASE`（项目已有 connectivity 工具链）

