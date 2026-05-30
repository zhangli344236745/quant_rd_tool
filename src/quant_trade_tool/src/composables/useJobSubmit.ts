import { ref } from "vue";
import { ElMessage } from "element-plus";
import { jobsApi, type JobRecord } from "@/api/jobs";
import { openJobDrawer } from "@/composables/jobDrawer";
import { extractError } from "@/api/http";

export function useJobSubmit() {
  const lastJobId = ref("");
  const polling = ref(false);

  async function waitForJob(jobId: string, onDone?: (r: Record<string, unknown>) => void) {
    polling.value = true;
    try {
      for (let i = 0; i < 600; i++) {
        const { data: job } = await jobsApi.get(jobId);
        if (job.status === "done") {
          const { data: result } = await jobsApi.result(jobId);
          onDone?.(result);
          return { job, result };
        }
        if (job.status === "failed" || job.status === "cancelled") {
          throw new Error(job.error || `任务 ${job.status}`);
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      throw new Error("任务超时");
    } finally {
      polling.value = false;
    }
  }

  async function submit(
    fn: () => Promise<{ data: { job_id: string } }>,
    opts?: { openDrawer?: boolean; wait?: boolean; onDone?: (r: Record<string, unknown>) => void },
  ) {
    try {
      const { data } = await fn();
      lastJobId.value = data.job_id;
      ElMessage.success(`任务已提交 ${data.job_id.slice(0, 8)}…`);
      if (opts?.openDrawer !== false) openJobDrawer();
      if (opts?.wait) return await waitForJob(data.job_id, opts.onDone);
      return { job_id: data.job_id };
    } catch (e) {
      ElMessage.error(extractError(e));
      throw e;
    }
  }

  return { lastJobId, polling, submit, waitForJob };
}

export function jobTypeLabel(type: string) {
  const map: Record<string, string> = {
    qlib_analyze: "Qlib",
    analyze_stock: "个股",
    backtest_run: "回测",
    macro_panel: "宏观",
    crypto_analyze: "Crypto",
  };
  return map[type] || type;
}
