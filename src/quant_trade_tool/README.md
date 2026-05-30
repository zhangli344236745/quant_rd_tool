# quant-trade-tool（前端）

Vue 3 + Element Plus 控制台，对接 `quant-rd-tool` 的 `/api/v1/crypto/*` 等接口。

## 启动

**1. 后端 API（项目根目录）**

```bash
cd quant_rd_tool
uv run quant-rd serve
# http://127.0.0.1:8765
```

**2. 前端**

```bash
cd src/quant_trade_tool
npm install
npm run dev
# http://127.0.0.1:5173
```

开发模式通过 Vite 将 `/api` 代理到 `8765`。

### 单端口部署（与 API 同进程）

```bash
npm run build
cd ../../..
uv run quant-rd serve
```

访问 `http://127.0.0.1:8765/` 即为控制台；`/api/v1` 为接口。生产构建下前端自动使用 `window.location.origin` 作为 API 根地址。

自定义 dist 路径：`QUANT_FRONTEND_DIST=/path/to/dist uv run quant-rd serve`

## 页面

| 路由 | 功能 |
|------|------|
| `/` | 健康检查 + Binance 连通性 |
| `/analyze` | 加密货币分析 |
| `/spot-bot` | 现货 Bot |
| `/perp-bot` | 永续 Bot（ATR/熔断/保护） |
| `/perp-portfolio` | 多标的组合 |
| `/schedules` | 定时任务 CRUD |
| `/astocks` | A 股公司列表与详情 |
| `/astocks/:code` | 基本信息 / 管理层 / 资讯 / 公告 |

## 生产构建

```bash
npm run build
# 产物在 dist/，可由 nginx 或 FastAPI StaticFiles 托管
```

自定义 API 地址：设置页填写 `http://host:8765`，或环境变量 `VITE_API_BASE`。
