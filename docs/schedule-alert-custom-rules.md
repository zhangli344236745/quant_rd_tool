# 调度自定义告警 — 条件格式

配置路径：`data/settings.json` → `schedule_alerts.custom_rules`（数组）

也可在 Web **定时任务** 页编辑，或通过 API `GET/POST /api/v1/crypto/schedules/alerts/rules`。

## 规则对象

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 唯一标识，用于冷却键 `custom:{id}` |
| `name` | 否 | 展示名称 |
| `enabled` | 否 | 默认 `true` |
| `job_ids` | 否 | 空数组 = 所有调度任务；否则仅匹配列出的任务 id |
| `symbol_scope` | 否 | `any_symbol`（默认）或 `all_symbols` |
| `logic` | 否 | `and`（默认）或 `or`，组合下方 `conditions` |
| `conditions` | 是 | 条件列表，见下表 |
| `message` | 否 | 告警文案模板，支持占位符 |

### symbol_scope

- **any_symbol**：本周期内**任意一个**成功分析的标的满足全部/任一条件（由 `logic` 决定）即告警。
- **all_symbols**：本周期内**每个**成功标的都必须满足，才告警（适合组合任务要「齐涨齐跌」）。

带 `error` 的标的不参与信号规则。

## 条件对象

```json
{ "field": "stance", "op": "eq", "value": "看涨" }
```

### field（字段）

| field | 别名 | 含义 |
|-------|------|------|
| `symbol` | `base`, `pair` | 标的，如 `BTC`、`ETH`；`BTC/USDT` 会规范为 `BTC` |
| `stance` | — | 综合立场：`看涨` / `看跌` / `中性` |
| `action` | — | 建议动作：`buy` / `sell` / `hold` / `long` / `short` 等（英文小写匹配） |
| `new_bars` | — | 本周期新增 K 线根数（数字） |
| `iv_alert_level` | `options_alert` | 期权 IV 告警：`normal` / `elevated` / `hot`（需调度分析开启 `with_options_vol`） |
| `options_stance` | — | 期权规则建议立场，如 `波动溢价偏高` |
| `iv_percentile` | `iv_pct` | IV 历史分位（0–100） |
| `iv_change_24h_pct` | `iv_change_24h` | 24h IV 变化（%） |
| `var_pct` | | 主置信度 VaR 损失占比（小数，0.05=5%） |
| `var_usdt` | | VaR USDT 金额 |
| `cvar_pct` | | CVaR 损失占比 |
| `var_99_pct` | | 99% 历史 VaR 占比 |
| `parametric_var_pct` | | 参数法 VaR |
| `mc_gbm_var_pct` | | 蒙特卡洛 GBM VaR |
| `mc_t_var_pct` | | 蒙特卡洛 Student-t VaR |

启用 VaR 字段：在 `schedule_alerts` 中设置 `var.enabled: true`，或自定义规则引用上述字段（调度周期会自动计算 VaR）。

### op（运算符）

| op | 适用 | value 示例 |
|----|------|------------|
| `eq` | 字符串、数字 | `"看涨"` |
| `neq` | 字符串、数字 | |
| `in` | 字符串、数字 | `["buy","long"]` 或 `"buy,long"` |
| `not_in` | 字符串、数字 | |
| `contains` | 字符串 | `"涨"`（子串） |
| `regex` | 字符串 | `"^看"` |
| `gt` / `gte` / `lt` / `lte` | 数字 | `1`（常用于 `new_bars`） |

### logic（条件组合）

- **and**：该标的需**同时**满足所有 conditions。
- **or**：满足**任意一条** condition 即可。

## message 占位符

`{job_id}` `{symbol}` `{pair}` `{stance}` `{action}` `{new_bars}` `{iv_alert_level}` `{options_stance}` `{iv_percentile}` `{iv_change_24h_pct}` `{var_pct}` `{var_usdt}` `{cvar_pct}` `{var_99_pct}` `{rule_id}` `{rule_name}`

## VaR 内置超限告警

在 `data/settings.json` → `schedule_alerts.var` 配置（与 `custom_rules` 同级）：

```json
{
  "schedule_alerts": {
    "var": {
      "enabled": true,
      "on_symbol_var_breach": true,
      "on_portfolio_var_breach": false,
      "on_rolling_var_breach": true,
      "max_var_pct": 0.05,
      "max_portfolio_var_pct_of_equity": 0.10,
      "confidence": 0.99,
      "notional_usdt": 10000,
      "lookback_bars": 360,
      "horizon_days": 1,
      "horizon_bars": 1,
      "timeframe": "4h",
      "mc_n_sims": 3000
    }
  }
}
```

- **on_symbol_var_breach**：任一标的 `var_pct >= max_var_pct` 时 Webhook 告警（`decision: var_symbol_breach`）。
- **on_rolling_var_breach**：最新一根 K 线实际收益低于当前 VaR 时告警（`decision: var_rolling_breach`）；需配置 `timeframe` / `horizon_bars`。
- **on_portfolio_var_breach**：永续账户组合 VaR 占权益 ≥ 阈值时告警（需 API Key）。
- **timeframe / horizon_bars**：支持 `1d` / `4h` / `1h` 日内 VaR；`horizon_bars` 为持有期（K 线根数）。
- **enabled**：为 true 时每个调度周期为各标的计算 VaR 并写入周期摘要（含 `var_breach`、`var_actual_return`），供自定义规则使用。

## 示例

### BTC 看涨

```json
{
  "id": "btc-bull",
  "name": "BTC 转多",
  "enabled": true,
  "job_ids": [],
  "symbol_scope": "any_symbol",
  "logic": "and",
  "conditions": [
    { "field": "symbol", "op": "eq", "value": "BTC" },
    { "field": "stance", "op": "eq", "value": "看涨" }
  ],
  "message": "[{job_id}] {symbol} → {stance} ({action})"
}
```

### ETH 卖出方向（限定任务 id）

```json
{
  "id": "eth-sell",
  "job_ids": ["btc-eth-5m"],
  "logic": "and",
  "conditions": [
    { "field": "symbol", "op": "eq", "value": "ETH" },
    { "field": "action", "op": "in", "value": ["sell", "short"] }
  ],
  "message": "{symbol} 出现偏空动作 {action}"
}
```

### BTC 期权 IV 偏高（hot）

```json
{
  "id": "btc-iv-hot",
  "name": "BTC IV 告警",
  "enabled": true,
  "conditions": [
    { "field": "symbol", "op": "eq", "value": "BTC" },
    { "field": "iv_alert_level", "op": "in", "value": ["hot", "elevated"] }
  ],
  "message": "[{job_id}] {symbol} 期权 IV {iv_alert_level}，分位 {iv_percentile}%，24h {iv_change_24h_pct}%"
}
```

### BTC VaR ≥ 5%

```json
{
  "id": "btc-var-5pct",
  "conditions": [
    { "field": "symbol", "op": "eq", "value": "BTC" },
    { "field": "var_pct", "op": "gte", "value": 0.05 }
  ],
  "message": "[{job_id}] {symbol} 1日 VaR {var_pct} ≈ {var_usdt} USDT"
}
```

### 增量 K 线 ≥ 5

```json
{
  "id": "sync-burst",
  "conditions": [
    { "field": "new_bars", "op": "gte", "value": 5 }
  ],
  "message": "{symbol} 本轮同步 {new_bars} 根新 K 线"
}
```

## Webhook

在 **定时任务** 页可单独开关「Webhook 推送」（`webhook_on_alert`，默认开启）。URL 来自 **Crypto 运营** 配置；周期失败、自定义规则、VaR 超限等告警触发时 POST（`kind: schedule_alert`，`decision` 为规则 id）。

关闭 `webhook_on_alert` 后不再发送 Webhook，不影响 Bark。

## Bark 手机推送

在 `schedule_alerts.bark` 配置（**定时任务** 页「手机推送」区块）：

```json
{
  "schedule_alerts": {
    "webhook_on_alert": true,
    "bark": {
      "enabled": false,
      "device_key": "",
      "server": "https://api.day.app"
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `enabled` | 是否推送；关闭时不调用 Bark |
| `device_key` | Bark App 中的 Key（可选）；也可在仓库根 `.env` 配置 `BARK_DEVICE_KEY`（推荐，不入库） |
| `server` | Bark API 根地址，默认 `https://api.day.app`；`.env` 可用 `BARK_SERVER` 覆盖 |

配置了 `BARK_DEVICE_KEY` 后，定时任务页可直接打开「Bark 推送」开关，无需在页面填写 Key。

**周期完成推送**（`schedule_alerts.on_cycle_complete`，默认开启）：每轮调度分析**成功跑完**后，向 Bark 发送各标的立场/动作摘要（`decision: cycle_complete`）。需同时开启「Bark 推送」；失败周期仍走「周期失败」等规则。

与 Webhook 独立：可同时开、只开其一或都关。告警标题为 `[{job_id}] {rule}`，正文为告警 `message`。

- 测试：`POST /api/v1/crypto/schedules/alerts/test-bark`，请求体带 `bark`（与页面表单一致）；成功后会自动写入 `settings.json`

## API

- `GET /api/v1/crypto/schedules/alerts/rules/format` — 返回说明与示例 JSON
- `POST /api/v1/crypto/schedules/alerts/test-bark` — 发送 Bark 测试推送
- 保存规则时若格式非法，返回 `400` 及校验错误信息
