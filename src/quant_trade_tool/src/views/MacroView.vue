<script setup lang="ts">
import { reactive, ref } from "vue";
import { jobsApi } from "@/api/jobs";
import { useJobSubmit } from "@/composables/useJobSubmit";

const form = reactive({
  code: "",
  countries: ["china", "united_states"],
  use_fred: true,
  use_fmp_peers: true,
  output_dir: "data/macro",
});

const { submit, polling } = useJobSubmit();
const markdown = ref("");
const error = ref("");

async function run(wait: boolean) {
  error.value = "";
  markdown.value = "";
  try {
    await submit(
      () =>
        jobsApi.macroPanel({
          ...form,
          code: form.code.trim() || null,
        }),
      {
        wait,
        onDone: (r) => {
          markdown.value = String(r.markdown || "");
        },
      },
    );
  } catch (e) {
    error.value = String(e);
  }
}
</script>

<template>
  <div>
    <h1 class="page-title">宏观面板</h1>
    <p class="page-desc">OpenBB 宏观 / 行业快照，可落盘 data/macro。</p>

    <el-row :gutter="20">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <el-form label-width="120px" size="small">
            <el-form-item label="股票代码">
              <el-input v-model="form.code" placeholder="可选，如 600519" />
            </el-form-item>
            <el-form-item label="国家">
              <el-select v-model="form.countries" multiple style="width: 100%">
                <el-option label="china" value="china" />
                <el-option label="united_states" value="united_states" />
                <el-option label="japan" value="japan" />
              </el-select>
            </el-form-item>
            <el-form-item label="FRED">
              <el-switch v-model="form.use_fred" />
            </el-form-item>
            <el-form-item label="FMP 同业">
              <el-switch v-model="form.use_fmp_peers" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="polling" @click="run(true)">生成</el-button>
              <el-button @click="run(false)">后台任务</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card shadow="never" class="panel-card" v-loading="polling">
          <template #header>Markdown</template>
          <el-alert v-if="error" type="error" :title="error" show-icon />
          <el-scrollbar v-else-if="markdown" max-height="560">
            <pre class="md">{{ markdown }}</pre>
          </el-scrollbar>
          <el-empty v-else description="提交任务后显示" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.md {
  margin: 0;
  padding: 12px;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
}
</style>
