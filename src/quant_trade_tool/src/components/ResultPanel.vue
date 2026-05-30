<script setup lang="ts">
defineProps<{
  loading?: boolean;
  result?: unknown;
  error?: string;
  title?: string;
}>();
</script>

<template>
  <el-card class="panel-card result-panel" shadow="never">
    <template #header>
      <div class="head">
        <span>{{ title || "执行结果" }}</span>
        <el-tag v-if="loading" type="info" size="small">运行中…</el-tag>
      </div>
    </template>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <div v-else-if="loading" v-loading="true" style="min-height: 120px" />
    <pre v-else-if="result" class="json-viewer">{{ JSON.stringify(result, null, 2) }}</pre>
    <el-empty v-else description="提交表单后显示结果" />
  </el-card>
</template>

<style scoped>
.result-panel {
  margin-top: 16px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
