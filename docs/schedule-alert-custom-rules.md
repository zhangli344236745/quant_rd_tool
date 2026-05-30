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

`{job_id}` `{symbol}` `{pair}` `{stance}` `{action}` `{new_bars}` `{rule_id}` `{rule_name}`

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

与「周期失败」等规则共用 **Crypto 运营** 中的 Webhook URL；自定义信号规则触发时同样 POST（`kind: schedule_alert`，`decision: custom:{id}`）。

## API

- `GET /api/v1/crypto/schedules/alerts/rules/format` — 返回说明与示例 JSON
- 保存规则时若格式非法，返回 `400` 及校验错误信息
