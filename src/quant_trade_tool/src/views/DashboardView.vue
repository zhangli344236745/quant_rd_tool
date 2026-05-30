<script setup lang="ts">
import { onMounted, ref } from "vue";
import { cryptoApi } from "@/api/crypto";
import { extractError } from "@/api/http";
import { docsUrl } from "@/config";

const health = ref<unknown>(null);
const connectivity = ref<unknown>(null);
const loading = ref(false);
const err = ref("");

async function refresh() {
  loading.value = true;
  err.value = "";
  try {
    const [h, c] = await Promise.all([
      cryptoApi.health(),
      cryptoApi.connectivity({ symbol: "BTC", timeframe: "5m" }),
    ]);
    health.value = h.data;
    connectivity.value = c.data;
  } catch (e) {
    err.value = extractError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);
</script>

<template>
  <div>
    <h1 class="page-title">系统概览</h1>
    <p class="page-desc">
      对接 quant-rd-tool 后端 API。请先启动
      <code class="mono">uv run quant-rd serve</code>，开发模式下前端通过 Vite 代理访问。
    </p>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never" class="panel-card">
          <template #header>服务状态</template>
          <el-button type="primary" :loading="loading" @click="refresh">刷新</el-button>
          <el-alert v-if="err" class="mt" type="error" :title="err" show-icon />
          <pre v-else-if="health" class="json-viewer mt">{{ JSON.stringify(health, null, 2) }}</pre>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" class="panel-card">
          <template #header>Binance 连接 (BTC 5m)</template>
          <pre v-if="connectivity" class="json-viewer">{{ JSON.stringify(connectivity, null, 2) }}</pre>
          <el-empty v-else description="点击刷新检测" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="panel-card mt-lg">
      <template #header>快捷入口</template>
      <el-space wrap>
        <router-link to="/tasks"><el-button type="primary">任务中心</el-button></router-link>
        <router-link to="/astocks"><el-button>A 股公司</el-button></router-link>
        <router-link to="/astocks-reports"><el-button>报告库</el-button></router-link>
        <router-link to="/stock-analyze"><el-button>个股分析</el-button></router-link>
        <router-link to="/backtest"><el-button>组合回测</el-button></router-link>
        <router-link to="/macro"><el-button>宏观面板</el-button></router-link>
        <router-link to="/analyze"><el-button>Crypto 行情</el-button></router-link>
        <router-link to="/crypto-ops"><el-button type="primary">Crypto 运营</el-button></router-link>
        <router-link to="/perp-bot"><el-button>永续 Bot</el-button></router-link>
        <router-link to="/perp-portfolio"><el-button>组合永续</el-button></router-link>
        <router-link to="/schedules"><el-button>定时任务</el-button></router-link>
        <a :href="docsUrl()" target="_blank"><el-button link>OpenAPI 文档</el-button></a>
      </el-space>
    </el-card>
  </div>
</template>

<style scoped>
.mt {
  margin-top: 12px;
}
.mt-lg {
  margin-top: 20px;
}
</style>
