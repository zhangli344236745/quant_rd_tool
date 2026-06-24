import { createRouter, createWebHistory } from "vue-router";
import MainLayout from "@/layouts/MainLayout.vue";

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      component: MainLayout,
      children: [
        { path: "", name: "dashboard", component: () => import("@/views/DashboardView.vue") },
        { path: "astocks", name: "astocks", component: () => import("@/views/AStockListView.vue") },
        {
          path: "astocks/:code",
          name: "astock-detail",
          component: () => import("@/views/AStockDetailView.vue"),
        },
        {
          path: "astocks-reports",
          name: "astock-reports",
          component: () => import("@/views/AStockReportsView.vue"),
        },
        {
          path: "astocks-compare",
          name: "astock-compare",
          component: () => import("@/views/AStockCompareView.vue"),
        },
        {
          path: "astocks-screener",
          name: "astock-screener",
          component: () => import("@/views/AStockScreenerView.vue"),
        },
        {
          path: "stock-workflow",
          name: "stock-workflow",
          component: () => import("@/views/StockWorkflowView.vue"),
        },
        {
          path: "stock-announcements",
          name: "stock-announcements",
          component: () => import("@/views/StockAnnouncementRadarView.vue"),
        },
        {
          path: "stock-ops",
          name: "stock-ops",
          component: () => import("@/views/StockOpsView.vue"),
        },
        {
          path: "stock-zipline",
          name: "stock-zipline",
          component: () => import("@/views/StockZiplineLabView.vue"),
        },
        {
          path: "stock-vbt",
          name: "stock-vbt",
          component: () => import("@/views/StockVbtLabView.vue"),
        },
        {
          path: "stock-var",
          name: "stock-var",
          component: () => import("@/views/StockVarView.vue"),
        },
        { path: "tasks", name: "tasks", component: () => import("@/views/TasksView.vue") },
        { path: "stock-analyze", name: "stock-analyze", component: () => import("@/views/StockAnalyzeView.vue") },
        { path: "backtest", name: "backtest", component: () => import("@/views/BacktestView.vue") },
        { path: "macro", name: "macro", component: () => import("@/views/MacroView.vue") },
        { path: "analyze", name: "analyze", component: () => import("@/views/AnalyzeView.vue") },
        {
          path: "crypto-options-vol",
          name: "crypto-options-vol",
          component: () => import("@/views/CryptoOptionsVolView.vue"),
        },
        {
          path: "crypto-var",
          name: "crypto-var",
          component: () => import("@/views/CryptoVarView.vue"),
        },
        {
          path: "crypto-workflow",
          name: "crypto-workflow",
          component: () => import("@/views/CryptoWorkflowView.vue"),
        },
        {
          path: "crypto-news",
          name: "crypto-news",
          component: () => import("@/views/CryptoNewsView.vue"),
        },
        {
          path: "crypto-zipline",
          name: "crypto-zipline",
          component: () => import("@/views/CryptoZiplineLabView.vue"),
        },
        { path: "spot-bot", name: "spot-bot", component: () => import("@/views/SpotBotView.vue") },
        { path: "crypto-carry", name: "crypto-carry", component: () => import("@/views/CryptoCarryView.vue") },
        { path: "crypto-polymarket", name: "crypto-polymarket", component: () => import("@/views/CryptoPolymarketView.vue") },
        { path: "crypto-hft", name: "crypto-hft", component: () => import("@/views/CryptoHftView.vue") },
        { path: "crypto-ws-hft", name: "crypto-ws-hft", component: () => import("@/views/CryptoWsHftView.vue") },
        { path: "crypto-ops", name: "crypto-ops", component: () => import("@/views/CryptoOpsView.vue") },
        { path: "perp-bot", name: "perp-bot", component: () => import("@/views/PerpBotView.vue") },
        {
          path: "perp-portfolio",
          name: "perp-portfolio",
          component: () => import("@/views/PerpPortfolioView.vue"),
        },
        { path: "schedules", name: "schedules", component: () => import("@/views/SchedulesView.vue") },
        {
          path: "finance-kb",
          name: "finance-kb",
          meta: { title: "金融知识库" },
          component: () => import("@/views/FinanceKnowledgeView.vue"),
        },
        { path: "settings", name: "settings", component: () => import("@/views/SettingsView.vue") },
      ],
    },
  ],
});

export default router;
