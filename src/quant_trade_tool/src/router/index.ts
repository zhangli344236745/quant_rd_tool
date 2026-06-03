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
        { path: "spot-bot", name: "spot-bot", component: () => import("@/views/SpotBotView.vue") },
        { path: "crypto-ops", name: "crypto-ops", component: () => import("@/views/CryptoOpsView.vue") },
        { path: "perp-bot", name: "perp-bot", component: () => import("@/views/PerpBotView.vue") },
        {
          path: "perp-portfolio",
          name: "perp-portfolio",
          component: () => import("@/views/PerpPortfolioView.vue"),
        },
        { path: "schedules", name: "schedules", component: () => import("@/views/SchedulesView.vue") },
        { path: "settings", name: "settings", component: () => import("@/views/SettingsView.vue") },
      ],
    },
  ],
});

export default router;
