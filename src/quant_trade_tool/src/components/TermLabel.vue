<script setup lang="ts">
defineProps<{
  label: string;
  hint: string;
  placement?: "top" | "bottom" | "left" | "right";
}>();
</script>

<template>
  <span class="term-label">
    <span>{{ label }}</span>
    <el-tooltip :content="hint" :placement="placement ?? 'top'" effect="dark" :show-after="200">
      <el-icon class="term-icon" :size="14"><QuestionFilled /></el-icon>
    </el-tooltip>
  </span>
</template>

<style scoped>
.term-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.term-icon {
  color: var(--el-text-color-secondary);
  cursor: help;
  vertical-align: middle;
}
.term-icon:hover {
  color: var(--el-color-primary);
}
</style>
