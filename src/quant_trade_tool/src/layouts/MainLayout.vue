<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import JobDrawer from "@/components/JobDrawer.vue";
import { jobDrawerVisible, openJobDrawer } from "@/composables/jobDrawer";
import { useActiveJobsPoll } from "@/composables/activeJobs";
import { docsUrl, getApiBase } from "@/config";

const route = useRoute();
const router = useRouter();
const { activeCount: jobBadge } = useActiveJobsPoll();

const active = computed(() => route.path);

type MenuItem = { path: string; icon: string; label: string };
type MenuGroup = { key: string; icon: string; label: string; items: MenuItem[] };

const rootMenus: MenuItem[] = [
  { path: "/", icon: "Odometer", label: "概览" },
  { path: "/tasks", icon: "List", label: "任务中心" },
  { path: "/finance-kb", icon: "ChatDotRound", label: "金融知识库" },
];

const groups: MenuGroup[] = [
  {
    key: "astock",
    icon: "OfficeBuilding",
    label: "A股管理",
    items: [
      { path: "/astocks", icon: "OfficeBuilding", label: "A 股公司" },
      { path: "/astocks-reports", icon: "FolderOpened", label: "报告库" },
      { path: "/astocks-screener", icon: "Filter", label: "选股器" },
      { path: "/stock-analyze", icon: "Document", label: "个股分析" },
      { path: "/stock-zipline", icon: "DataLine", label: "策略实验室" },
      { path: "/backtest", icon: "DataLine", label: "组合回测" },
      { path: "/macro", icon: "MapLocation", label: "宏观面板" },
    ],
  },
  {
    key: "crypto",
    icon: "Coin",
    label: "数字货币管理",
    items: [
      { path: "/analyze", icon: "TrendCharts", label: "Crypto 行情" },
      { path: "/crypto-options-vol", icon: "DataAnalysis", label: "期权波动" },
      { path: "/crypto-var", icon: "Warning", label: "风险 VaR" },
      { path: "/crypto-news", icon: "Bell", label: "舆论雷达" },
      { path: "/crypto-zipline", icon: "DataLine", label: "策略实验室" },
      { path: "/crypto-ops", icon: "Monitor", label: "Crypto 运营" },
      { path: "/spot-bot", icon: "Coin", label: "现货 Bot" },
      { path: "/perp-bot", icon: "Histogram", label: "永续 Bot" },
      { path: "/perp-portfolio", icon: "Grid", label: "组合永续" },
    ],
  },
];

const tailMenus: MenuItem[] = [
  { path: "/schedules", icon: "Timer", label: "定时任务" },
  { path: "/settings", icon: "Setting", label: "设置" },
];

const apiHint = computed(() => getApiBase() || "代理 → 127.0.0.1:8765");
</script>

<template>
  <el-container class="shell">
    <el-aside width="220px" class="aside">
      <div class="brand">
        <span class="brand-mark" />
        <div>
          <div class="brand-title">Quant Console</div>
          <div class="brand-sub mono">{{ apiHint }}</div>
        </div>
      </div>
      <el-menu
        :default-active="active"
        background-color="transparent"
        text-color="#8b9cb3"
        active-text-color="#3dd6c3"
        router
      >
        <el-menu-item v-for="m in rootMenus" :key="m.path" :index="m.path" @click="router.push(m.path)">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.label }}</span>
        </el-menu-item>

        <el-sub-menu v-for="g in groups" :key="g.key" :index="`group:${g.key}`">
          <template #title>
            <el-icon><component :is="g.icon" /></el-icon>
            <span>{{ g.label }}</span>
          </template>
          <el-menu-item v-for="m in g.items" :key="m.path" :index="m.path" @click="router.push(m.path)">
            <el-icon><component :is="m.icon" /></el-icon>
            <span>{{ m.label }}</span>
          </el-menu-item>
        </el-sub-menu>

        <el-menu-item v-for="m in tailMenus" :key="m.path" :index="m.path" @click="router.push(m.path)">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="header-crumb mono">{{ route.meta?.title || route.name }}</span>
        <el-badge :value="jobBadge" :hidden="jobBadge === 0" class="job-badge">
          <el-button size="small" @click="openJobDrawer">任务</el-button>
        </el-badge>
        <a class="docs-link" :href="docsUrl()" target="_blank" rel="noopener">API Docs ↗</a>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
    <JobDrawer />
  </el-container>
</template>

<style scoped>
.shell {
  height: 100vh;
  background: var(--bg-deep);
}

.aside {
  border-right: 1px solid var(--border);
  background: linear-gradient(180deg, #0e1219 0%, #0c0f14 100%);
  padding-top: 12px;
}

.brand {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 8px 16px 20px;
}

.brand-mark {
  width: 10px;
  height: 36px;
  border-radius: 4px;
  background: linear-gradient(180deg, var(--accent), #2a9d8f);
  box-shadow: 0 0 20px var(--accent-dim);
}

.brand-title {
  font-weight: 700;
  font-size: 1rem;
  letter-spacing: -0.02em;
}

.brand-sub {
  font-size: 10px;
  color: var(--text-muted);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-badge {
  margin-right: 16px;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  background: rgba(18, 23, 31, 0.6);
  backdrop-filter: blur(8px);
}

.header-crumb {
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 12px;
  color: var(--text-muted);
}

.docs-link {
  color: var(--accent);
  font-size: 13px;
  text-decoration: none;
}

.docs-link:hover {
  text-decoration: underline;
}

.main {
  padding: 24px;
  overflow: auto;
}
</style>
