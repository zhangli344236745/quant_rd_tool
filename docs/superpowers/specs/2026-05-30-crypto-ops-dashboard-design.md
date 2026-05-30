# Crypto 运营看板 — 设计规格（C 定位 · Phase 3）

## 目标

为个人/小团队提供 **永续 / 调度 / 遥测** 统一只读运营视图，不新增实盘能力。

## 范围

- `GET /crypto/ops/summary` — 调度列表、perp 状态文件、遥测摘要
- `GET /crypto/perp/telemetry` — 按日 tail JSONL
- `GET /crypto/perp/states` — `perp_state_*.json` + protection 摘要
- 前端 `CryptoOpsView` — 统计卡片、状态卡、遥测表、调度表、快捷 signal-only

## 非目标

- Webhook 告警、Kill Switch API、图表库（后续）

## 批准

与路线图 Phase 3 一致；已实现于 2026-05-30。
