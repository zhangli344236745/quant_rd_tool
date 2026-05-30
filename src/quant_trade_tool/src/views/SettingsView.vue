<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getApiBase, setApiBase, docsUrl } from "@/config";
import {
  enterpriseApi,
  getStoredApiKey,
  setStoredApiKey,
  setStoredBearer,
} from "@/api/enterprise";
import { settingsApi } from "@/api/settings";
import { extractError } from "@/api/http";

const entEnabled = ref(false);
const entRequireAuth = ref(false);
const entAudit = ref(true);
const entApiKey = ref(getStoredApiKey());
const entAdminPass = ref("");
const entStatus = ref("");
const auditItems = ref<Record<string, unknown>[]>([]);

const apiBase = ref(getApiBase());
const useProxy = ref(!getApiBase());
const httpProxy = ref("");
const httpsProxy = ref("");
const noProxy = ref("push2.eastmoney.com,82.push2.eastmoney.com");

function saveApi() {
  if (useProxy.value) {
    localStorage.removeItem("quant_trade_api_base");
    apiBase.value = "";
    ElMessage.success("已使用 Vite 代理（/api → 8765）");
    return;
  }
  setApiBase(apiBase.value);
  ElMessage.success("API 地址已保存");
}

async function loadNetwork() {
  try {
    const { data } = await settingsApi.getNetwork();
    httpProxy.value = data.http_proxy || "";
    httpsProxy.value = data.https_proxy || "";
    noProxy.value = data.no_proxy || noProxy.value;
  } catch {
    /* optional before first save */
  }
}

async function saveNetwork() {
  try {
    await settingsApi.saveNetwork({
      http_proxy: httpProxy.value,
      https_proxy: httpsProxy.value,
      no_proxy: noProxy.value,
    });
    ElMessage.success("网络代理已保存（新任务生效）");
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function exportBundle() {
  try {
    const { data } = await settingsApi.exportBundle();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "quant-rd-settings.json";
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function onImportFile(uploadFile: { raw?: File }) {
  const file = uploadFile.raw;
  if (!file) return;
  try {
    const text = await file.text();
    const body = JSON.parse(text);
    await settingsApi.importBundle(body);
    await loadNetwork();
    ElMessage.success("已导入设置");
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function loadEnterprise() {
  try {
    const { data } = await enterpriseApi.status();
    entEnabled.value = data.enabled;
    entRequireAuth.value = data.require_auth;
    entAudit.value = data.audit_enabled;
    entStatus.value = data.login_available ? "支持管理员密码登录" : "未配置 QUANT_RD_ADMIN_PASSWORD";
    if (data.enabled && data.audit_enabled) {
      const audit = await enterpriseApi.audit({ limit: 20 });
      auditItems.value = [...audit.data.items].reverse();
    }
  } catch {
    /* optional */
  }
}

async function saveEnterpriseLocal() {
  setStoredApiKey(entApiKey.value.trim());
  ElMessage.success("API Key 已保存到浏览器");
}

async function saveEnterpriseServer() {
  try {
    await enterpriseApi.saveSettings({
      enabled: entEnabled.value,
      require_auth: entRequireAuth.value,
      audit_enabled: entAudit.value,
    });
    ElMessage.success("企业模块配置已写入 settings.json");
    await loadEnterprise();
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

async function tryLogin() {
  try {
    const { data } = await enterpriseApi.login(entAdminPass.value);
    setStoredBearer(data.token);
    ElMessage.success("已登录，Token 已保存");
    entAdminPass.value = "";
    await loadEnterprise();
  } catch (e) {
    ElMessage.error(extractError(e));
  }
}

onMounted(async () => {
  await loadNetwork();
  await loadEnterprise();
});
</script>

<template>
  <div>
    <h1 class="page-title">设置</h1>
    <p class="page-desc">API 地址、HTTP 代理（东财/akshare）、自选与配置导出。</p>

    <el-card shadow="never" class="panel-card mb-card">
      <template #header>API</template>
      <el-form label-width="140px">
        <el-form-item label="使用开发代理">
          <el-switch v-model="useProxy" active-text="是 (/api)" inactive-text="否" />
        </el-form-item>
        <el-form-item v-if="!useProxy" label="API 根地址">
          <el-input v-model="apiBase" placeholder="http://127.0.0.1:8765" class="mono" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveApi">保存 API</el-button>
          <a :href="docsUrl()" target="_blank" class="ml"><el-button link>Swagger</el-button></a>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="panel-card mb-card">
      <template #header>网络代理</template>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="若出现 ProxyError，可清空代理或把东财域名加入 no_proxy。修改后需重启 serve 或等待新任务。"
        class="mb"
      />
      <el-form label-width="140px">
        <el-form-item label="HTTP_PROXY">
          <el-input v-model="httpProxy" placeholder="留空表示不使用" class="mono" />
        </el-form-item>
        <el-form-item label="HTTPS_PROXY">
          <el-input v-model="httpsProxy" class="mono" />
        </el-form-item>
        <el-form-item label="NO_PROXY">
          <el-input v-model="noProxy" class="mono" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveNetwork">保存代理</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="panel-card mb-card">
      <template #header>企业模块（可选 · 双线之企业轨）</template>
      <p class="page-desc block-desc">
        默认关闭，与单机 C 轨兼容。内网部署时可启用 API Key、审计；规格见
        <code>docs/superpowers/specs/2026-05-30-dual-track-c-plus-enterprise-design.md</code>
      </p>
      <el-form label-width="160px">
        <el-form-item label="启用企业模块">
          <el-switch v-model="entEnabled" />
        </el-form-item>
        <el-form-item label="变更 API 需认证">
          <el-switch v-model="entRequireAuth" :disabled="!entEnabled" />
        </el-form-item>
        <el-form-item label="审计日志">
          <el-switch v-model="entAudit" :disabled="!entEnabled" />
        </el-form-item>
        <el-form-item label="浏览器 API Key">
          <el-input v-model="entApiKey" class="mono" placeholder="X-API-Key" />
        </el-form-item>
        <el-form-item label="管理员登录">
          <el-input v-model="entAdminPass" type="password" show-password placeholder="QUANT_RD_ADMIN_PASSWORD" />
          <span class="hint">{{ entStatus }}</span>
        </el-form-item>
        <el-form-item>
          <el-button @click="saveEnterpriseLocal">保存 Key 到浏览器</el-button>
          <el-button type="primary" @click="saveEnterpriseServer">写入服务端配置</el-button>
          <el-button :disabled="!entEnabled" @click="tryLogin">登录</el-button>
        </el-form-item>
      </el-form>
      <el-table v-if="auditItems.length" :data="auditItems" size="small" max-height="200">
        <el-table-column prop="ts" label="时间" width="170" />
        <el-table-column prop="method" label="方法" width="70" />
        <el-table-column prop="path" label="路径" min-width="160" show-overflow-tooltip />
        <el-table-column prop="principal" label="身份" width="90" />
        <el-table-column prop="status" label="状态" width="60" />
      </el-table>
    </el-card>

    <el-card shadow="never" class="panel-card" style="max-width: 640px">
      <template #header>备份</template>
      <el-button @click="exportBundle">导出 JSON</el-button>
      <el-upload
        :auto-upload="false"
        :show-file-list="false"
        accept="application/json"
        style="display: inline-block; margin-left: 12px"
        @change="onImportFile"
      >
        <el-button>导入 JSON</el-button>
      </el-upload>
    </el-card>
  </div>
</template>

<style scoped>
.mb-card {
  margin-bottom: 20px;
  max-width: 720px;
}
.mb {
  margin-bottom: 12px;
}
.ml {
  margin-left: 8px;
}
.block-desc {
  margin: 0 0 16px;
  font-size: 13px;
}
.hint {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-muted);
}
</style>
