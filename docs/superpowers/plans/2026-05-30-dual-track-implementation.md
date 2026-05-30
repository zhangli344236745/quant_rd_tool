# 双线实施计划

**规格**：[2026-05-30-dual-track-c-plus-enterprise-design.md](../specs/2026-05-30-dual-track-c-plus-enterprise-design.md)

## 轨道 A — 企业 MVP v0.1

| 任务 | 状态 |
|------|------|
| `enterprise/` 配置、认证、审计、中间件 | done |
| `/api/v1/enterprise/*` 路由 | done |
| 前端：设置页 API Key + 审计 | done |

## 轨道 B — C+ P0

| 任务 | 状态 |
|------|------|
| 报告归档 `reports/{ts}.json` + diff API | done |
| Job 事件表 + SSE `/jobs/{id}/events` + 自动重试 | done |
| 选股器 + `/jobs/screener-enqueue` | done |
| 前端：选股器页、详情 diff、Job SSE composable | done |

## 原则

- 企业模块 **默认关闭**，不破坏现有单机用户。
- C+ 功能不依赖 `enterprise.enabled`。
- 企业 v0.2 候选：RBAC 只读/读写角色、审计导出 CSV。
